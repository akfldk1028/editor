using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Xunit;

namespace DwgIntelligence.CadIo.Tests;

public sealed class DwgRoundTripTests
{
    private static readonly string[] ExpectedCandidates =
        ["AC1014", "AC1015", "AC1018", "AC1024", "AC1027", "AC1032"];

    [Fact]
    public void PolicyLoadsOnlyACompleteImmutableVerifiedAllowlist()
    {
        using var fixture = PolicyFixture.Create(
            verifiedVersion: "AC1032");

        DwgVersionPolicy policy = DwgVersionPolicy.Load(
            fixture.ManifestPath);
        File.WriteAllText(
            fixture.ManifestPath,
            ManifestJson(verifiedVersion: "AC1014"));

        Assert.Equal(
            ExpectedCandidates,
            DwgVersionPolicy.CandidateVersions);
        Assert.Equal(ExpectedCandidates, policy.Entries.Select(
            entry => entry.Version));
        Assert.True(policy.IsAllowed("AC1032"));
        Assert.False(policy.IsAllowed("AC1014"));
        Assert.False(policy.IsAllowed("AC9999"));
        Assert.Throws<NotSupportedException>(
            () => ((IList<DwgVersionEvidence>)policy.Entries).Add(
                new DwgVersionEvidence(
                    "AC9999",
                    "A".Repeat(64),
                    true,
                    "B".Repeat(64))));
    }

    [Theory]
    [MemberData(nameof(InvalidManifestJson))]
    public void PolicyRejectsIncompleteUnknownDuplicateOrMalformedEvidence(
        string json)
    {
        using var fixture = PolicyFixture.Create(json: json);

        CadIoException error = Assert.Throws<CadIoException>(
            () => DwgVersionPolicy.Load(fixture.ManifestPath));

        Assert.Equal("DWG_POLICY_INVALID", error.Code);
    }

    [Fact]
    public void WriterRejectsAnUnverifiedDwgVersionBeforeTouchingOutput()
    {
        using var fixture = PolicyFixture.Create(
            verifiedVersion: "AC1032");
        DwgVersionPolicy policy = DwgVersionPolicy.Load(
            fixture.ManifestPath);
        string missingSource = Path.Combine(fixture.Root, "missing.dwg");
        string output = Path.Combine(fixture.Root, "must-not-exist.dwg");
        CadIoRequest request = CadIoRequest.Parse(JsonSerializer.Serialize(
            new
            {
                schemaVersion = "cad-io/v1",
                operation = "write-copy",
                sourcePath = missingSource,
                temporaryOutputPath = output,
                format = "dwg",
                version = "AC1027",
                lineage = Array.Empty<object>()
            }));

        CadIoException error = Assert.Throws<CadIoException>(
            () => CadFileWriter.Write(request, policy));

        Assert.Equal("DWG_VERSION_NOT_ALLOWLISTED", error.Code);
        Assert.False(File.Exists(output));
    }

    [Fact]
    public void CheckedInPolicyIsCompleteReleaseReadyAndMatchesProbeFixture()
    {
        string root = RepositoryRoot();
        string manifestPath = Path.Combine(
            root,
            "tests",
            "fixtures",
            "dwg",
            "roundtrip-manifest.json");
        string sourcePath = Path.Combine(
            root,
            "tests",
            "fixtures",
            "dwg",
            "export_sample.dwg");

        DwgVersionPolicy policy = DwgVersionPolicy.Load(manifestPath);
        string sourceHash = Convert.ToHexString(
            SHA256.HashData(File.ReadAllBytes(sourcePath)));
        string invariantHash = DwgRoundTripInvariant.ComputeSha256(
            DwgIndexBuilder.Build(sourcePath));
        DwgVersionEvidence[] verified = policy.Entries
            .Where(entry => entry.Verified)
            .ToArray();

        Assert.NotEmpty(verified);
        Assert.All(
            verified,
            entry =>
            {
                Assert.Equal(sourceHash, entry.ProbeFixtureSha256);
                Assert.Equal(invariantHash, entry.InvariantSha256);
            });
    }

    [Fact]
    public void ProbeOwnershipAndReportPathsAreNotFixtureEntries()
    {
        string manifest = File.ReadAllText(Path.Combine(
            RepositoryRoot(),
            "tests",
            "fixtures",
            "manifest.json"));

        Assert.DoesNotContain(
            DwgVersionProbe.OwnerMarkerName,
            manifest);
        Assert.DoesNotContain(
            "dwg-version-probe-",
            manifest);
    }

    [Fact]
    public void VerifiedFixtureVersionsWriteReopenAndPreserveInvariant()
    {
        string root = RepositoryRoot();
        string manifestPath = Path.Combine(
            root,
            "tests",
            "fixtures",
            "dwg",
            "roundtrip-manifest.json");
        string sourcePath = Path.Combine(
            root,
            "tests",
            "fixtures",
            "dwg",
            "export_sample.dwg");
        string sourceHash = Sha256(sourcePath);
        DwgVersionPolicy policy = DwgVersionPolicy.Load(manifestPath);
        CadIndex sourceIndex = DwgIndexBuilder.Build(sourcePath);
        string sourceInvariant =
            DwgRoundTripInvariant.ComputeSha256(sourceIndex);
        string outputRoot = Path.Combine(
            Path.GetTempPath(),
            $"dwg-roundtrip-{Guid.NewGuid():N}");
        Directory.CreateDirectory(outputRoot);
        try
        {
            foreach (
                DwgVersionEvidence entry
                in policy.Entries.Where(entry => entry.Verified))
            {
                string outputPath = Path.Combine(
                    outputRoot,
                    $"{entry.Version}.dwg");
                CadIoRequest request = CadIoRequest.Parse(
                    JsonSerializer.Serialize(new
                    {
                        schemaVersion = "cad-io/v1",
                        operation = "write-copy",
                        sourcePath,
                        temporaryOutputPath = outputPath,
                        format = "dwg",
                        version = entry.Version,
                        lineage = Array.Empty<object>()
                    }));

                CadIoSuccessResponse response = CadFileWriter.Write(
                    request,
                    policy);
                CadIndex reopened = DwgIndexBuilder.Build(outputPath);

                Assert.Equal(entry.Version, response.Version);
                Assert.Equal(
                    entry.Version,
                    reopened.Drawing.FileVersion);
                Assert.Equal(
                    sourceInvariant,
                    DwgRoundTripInvariant.ComputeSha256(reopened));
                Assert.Equal(sourceHash, Sha256(sourcePath));
            }
        }
        finally
        {
            Directory.Delete(outputRoot, recursive: true);
        }
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task ProbePublicationFailurePreservesTargetAndCleansTemps(
        bool targetIsDirectory)
    {
        string root = RepositoryRoot();
        string sourcePath = Path.Combine(
            root,
            "tests",
            "fixtures",
            "dwg",
            "export_sample.dwg");
        string testRoot = Path.Combine(
            Path.GetTempPath(),
            $"dwg-probe-publication-{Guid.NewGuid():N}");
        string processTemp = Path.Combine(testRoot, "process-temp");
        string outputPath = Path.Combine(testRoot, "report.json");
        Directory.CreateDirectory(processTemp);
        if (targetIsDirectory)
        {
            Directory.CreateDirectory(outputPath);
            File.WriteAllText(
                Path.Combine(outputPath, "owner.txt"),
                "ORIGINAL");
        }
        else
        {
            File.WriteAllText(outputPath, "ORIGINAL");
        }
        try
        {
            ProcessResult result = await RunProbeHost(
                root,
                sourcePath,
                outputPath,
                processTemp);

            Assert.NotEqual(0, result.ExitCode);
            Assert.Single(
                result.Stdout.Split(
                    Environment.NewLine,
                    StringSplitOptions.RemoveEmptyEntries));
            using JsonDocument response =
                JsonDocument.Parse(result.Stdout);
            Assert.Equal(
                "error",
                response.RootElement
                    .GetProperty("status")
                    .GetString());
            Assert.InRange(
                Encoding.UTF8.GetByteCount(result.Stdout),
                1,
                CadIoRequest.MaxJsonBytes);
            Assert.Equal(
                "CAD I/O request failed.",
                result.Stderr.Trim());
            Assert.DoesNotContain(testRoot, result.Stdout + result.Stderr);
            if (targetIsDirectory)
            {
                Assert.True(Directory.Exists(outputPath));
                Assert.Equal(
                    "ORIGINAL",
                    File.ReadAllText(
                        Path.Combine(outputPath, "owner.txt")));
            }
            else
            {
                Assert.Equal("ORIGINAL", File.ReadAllText(outputPath));
            }
            Assert.Empty(Directory.EnumerateFileSystemEntries(
                testRoot,
                ".report.json.*.tmp"));
            Assert.Empty(Directory.EnumerateDirectories(
                processTemp,
                "dwg-version-probe-*"));
        }
        finally
        {
            Directory.Delete(testRoot, recursive: true);
        }
    }

    [Fact]
    public async Task ProbeSuccessfulPublicationLeavesNoTemps()
    {
        string root = RepositoryRoot();
        string sourcePath = Path.Combine(
            root,
            "tests",
            "fixtures",
            "dwg",
            "export_sample.dwg");
        string sourceHash = Sha256(sourcePath);
        string testRoot = Path.Combine(
            Path.GetTempPath(),
            $"dwg-probe-success-{Guid.NewGuid():N}");
        string processTemp = Path.Combine(testRoot, "process-temp");
        string outputPath = Path.Combine(testRoot, "report.json");
        Directory.CreateDirectory(processTemp);
        try
        {
            ProcessResult result = await RunProbeHost(
                root,
                sourcePath,
                outputPath,
                processTemp);

            Assert.Equal(0, result.ExitCode);
            Assert.Equal("", result.Stdout);
            Assert.Equal("", result.Stderr);
            using JsonDocument report = JsonDocument.Parse(
                File.ReadAllText(outputPath));
            Assert.Equal(
                DwgVersionPolicy.CandidateVersions.Count,
                report.RootElement
                    .GetProperty("candidates")
                    .GetArrayLength());
            Assert.Empty(Directory.EnumerateFileSystemEntries(
                testRoot,
                ".report.json.*.tmp"));
            Assert.Empty(Directory.EnumerateDirectories(
                processTemp,
                "dwg-version-probe-*"));
            Assert.Equal(sourceHash, Sha256(sourcePath));
        }
        finally
        {
            Directory.Delete(testRoot, recursive: true);
        }
    }

    [Theory]
    [InlineData(".DWG")]
    [InlineData(".Dwg")]
    public void ProbeAcceptsDwgExtensionCaseInsensitively(string extension)
    {
        string sourceFixture = Path.Combine(
            RepositoryRoot(),
            "tests",
            "fixtures",
            "dwg",
            "export_sample.dwg");
        string testRoot = Path.Combine(
            Path.GetTempPath(),
            $"dwg-probe-extension-{Guid.NewGuid():N}");
        string sourcePath = Path.Combine(testRoot, $"source{extension}");
        string outputPath = Path.Combine(testRoot, "report.json");
        Directory.CreateDirectory(testRoot);
        File.Copy(sourceFixture, sourcePath);
        try
        {
            DwgVersionProbe.Run(sourcePath, outputPath);

            using JsonDocument report = JsonDocument.Parse(
                File.ReadAllText(outputPath));
            Assert.Equal(
                5,
                report.RootElement
                    .GetProperty("candidates")
                    .EnumerateArray()
                    .Count(candidate =>
                        candidate
                            .GetProperty("verified")
                            .GetBoolean()));
        }
        finally
        {
            Directory.Delete(testRoot, recursive: true);
        }
    }

    [Fact]
    public void ProbeRejectsANonDwgExtension()
    {
        string sourceFixture = Path.Combine(
            RepositoryRoot(),
            "tests",
            "fixtures",
            "dwg",
            "export_sample.dwg");
        string testRoot = Path.Combine(
            Path.GetTempPath(),
            $"dwg-probe-extension-{Guid.NewGuid():N}");
        string sourcePath = Path.Combine(testRoot, "source.dxf");
        string outputPath = Path.Combine(testRoot, "report.json");
        Directory.CreateDirectory(testRoot);
        File.Copy(sourceFixture, sourcePath);
        try
        {
            CadIoException error = Assert.Throws<CadIoException>(
                () => DwgVersionProbe.Run(sourcePath, outputPath));

            Assert.Equal("DWG_PROBE_INVALID", error.Code);
            Assert.False(File.Exists(outputPath));
        }
        finally
        {
            Directory.Delete(testRoot, recursive: true);
        }
    }

    [Fact]
    public void ProbeRejectsCandidatePathReplacementWithoutTouchingReplacement()
    {
        string sourcePath = Path.Combine(
            RepositoryRoot(),
            "tests",
            "fixtures",
            "dwg",
            "export_sample.dwg");
        string testRoot = Path.Combine(
            Path.GetTempPath(),
            $"dwg-probe-candidate-swap-{Guid.NewGuid():N}");
        string outputPath = Path.Combine(testRoot, "report.json");
        string? ownedMovedPath = null;
        string? replacementPath = null;
        Directory.CreateDirectory(testRoot);
        try
        {
            CadIoException error = Assert.Throws<CadIoException>(
                () => DwgVersionProbe.Run(
                    sourcePath,
                    outputPath,
                    afterCandidateWrite: candidatePath =>
                    {
                        if (
                            !candidatePath.EndsWith(
                                "AC1032.dwg",
                                StringComparison.Ordinal))
                        {
                            return;
                        }
                        ownedMovedPath = Path.Combine(
                            testRoot,
                            "owned-ac1032.moved");
                        File.Move(candidatePath, ownedMovedPath);
                        File.WriteAllText(candidatePath, "UNRELATED");
                        replacementPath = candidatePath;
                    },
                    beforeCleanup: null));

            Assert.Equal("DWG_PROBE_CLEANUP_FAILED", error.Code);
            Assert.False(File.Exists(outputPath));
            Assert.NotNull(replacementPath);
            Assert.Equal("UNRELATED", File.ReadAllText(replacementPath));
            Assert.NotNull(ownedMovedPath);
            Assert.Equal(0, new FileInfo(ownedMovedPath).Length);
        }
        finally
        {
            string? candidateRoot = replacementPath is null
                ? null
                : Path.GetDirectoryName(replacementPath);
            if (
                candidateRoot is not null
                && Directory.Exists(candidateRoot))
            {
                Directory.Delete(candidateRoot, recursive: true);
            }
            if (Directory.Exists(testRoot))
            {
                Directory.Delete(testRoot, recursive: true);
            }
        }
    }

    [Fact]
    public void ProbeCleanupPreservesAnUnknownChildInAValidOwnedRoot()
    {
        string sourcePath = Path.Combine(
            RepositoryRoot(),
            "tests",
            "fixtures",
            "dwg",
            "export_sample.dwg");
        string testRoot = Path.Combine(
            Path.GetTempPath(),
            $"dwg-probe-unknown-child-{Guid.NewGuid():N}");
        string outputPath = Path.Combine(testRoot, "report.json");
        string? unknownPath = null;
        Directory.CreateDirectory(testRoot);
        try
        {
            CadIoException error = Assert.Throws<CadIoException>(
                () => DwgVersionProbe.Run(
                    sourcePath,
                    outputPath,
                    afterCandidateWrite: null,
                    beforeCleanup: candidateRoot =>
                    {
                        unknownPath = Path.Combine(
                            candidateRoot,
                            "unrelated.txt");
                        File.WriteAllText(unknownPath, "UNRELATED");
                    }));

            Assert.Equal("DWG_PROBE_CLEANUP_FAILED", error.Code);
            Assert.False(File.Exists(outputPath));
            Assert.NotNull(unknownPath);
            Assert.Equal("UNRELATED", File.ReadAllText(unknownPath));
        }
        finally
        {
            string? candidateRoot = unknownPath is null
                ? null
                : Path.GetDirectoryName(unknownPath);
            if (
                candidateRoot is not null
                && Directory.Exists(candidateRoot))
            {
                Directory.Delete(candidateRoot, recursive: true);
            }
            if (Directory.Exists(testRoot))
            {
                Directory.Delete(testRoot, recursive: true);
            }
        }
    }

    [Fact]
    public void ProbeDeletesTheVerifiedInodeAfterItsPathIsReplaced()
    {
        string sourcePath = Path.Combine(
            RepositoryRoot(),
            "tests",
            "fixtures",
            "dwg",
            "export_sample.dwg");
        string testRoot = Path.Combine(
            Path.GetTempPath(),
            $"dwg-probe-delete-swap-{Guid.NewGuid():N}");
        string outputPath = Path.Combine(testRoot, "report.json");
        string? replacementPath = null;
        string? movedOwnedPath = null;
        string? originalCandidateRoot = null;
        Directory.CreateDirectory(testRoot);
        try
        {
            CadIoException error = Assert.Throws<CadIoException>(
                () => DwgVersionProbe.Run(
                    sourcePath,
                    outputPath,
                    afterCandidateWrite: null,
                    beforeCleanup: candidateRoot =>
                    {
                        originalCandidateRoot = candidateRoot;
                    },
                    afterDeleteIdentityVerified: candidatePath =>
                    {
                        if (
                            !candidatePath.EndsWith(
                                "AC1032.dwg",
                                StringComparison.Ordinal))
                        {
                            return;
                        }
                        movedOwnedPath = Path.Combine(
                            testRoot,
                            "verified-owned.moved");
                        File.Move(candidatePath, movedOwnedPath);
                        File.WriteAllText(candidatePath, "UNRELATED");
                        replacementPath = candidatePath;
                    },
                    beforeReportTempCleanup: null));

            Assert.Equal("DWG_PROBE_CLEANUP_FAILED", error.Code);
            Assert.False(File.Exists(outputPath));
            Assert.NotNull(replacementPath);
            Assert.NotNull(originalCandidateRoot);
            replacementPath = Path.Combine(
                originalCandidateRoot,
                "AC1032.dwg");
            Assert.Equal("UNRELATED", File.ReadAllText(replacementPath));
            Assert.NotNull(movedOwnedPath);
            Assert.False(File.Exists(movedOwnedPath));
        }
        finally
        {
            string? candidateRoot = replacementPath is null
                ? null
                : Path.GetDirectoryName(replacementPath);
            if (
                candidateRoot is not null
                && Directory.Exists(candidateRoot))
            {
                Directory.Delete(candidateRoot, recursive: true);
            }
            if (Directory.Exists(testRoot))
            {
                Directory.Delete(testRoot, recursive: true);
            }
        }
    }

    [Fact]
    public void ProbePublicationFailureDeletesOnlyItsOwnedReportTemp()
    {
        string sourcePath = Path.Combine(
            RepositoryRoot(),
            "tests",
            "fixtures",
            "dwg",
            "export_sample.dwg");
        string testRoot = Path.Combine(
            Path.GetTempPath(),
            $"dwg-probe-report-swap-{Guid.NewGuid():N}");
        string outputPath = Path.Combine(testRoot, "report.json");
        string? replacementPath = null;
        string? movedOwnedPath = null;
        Directory.CreateDirectory(testRoot);
        File.WriteAllText(outputPath, "ORIGINAL");
        try
        {
            Assert.ThrowsAny<Exception>(
                () => DwgVersionProbe.Run(
                    sourcePath,
                    outputPath,
                    afterCandidateWrite: null,
                    beforeCleanup: null,
                    afterDeleteIdentityVerified: null,
                    beforeReportTempCleanup: temporaryPath =>
                    {
                        movedOwnedPath = Path.Combine(
                            testRoot,
                            "owned-report.moved");
                        File.Move(temporaryPath, movedOwnedPath);
                        File.WriteAllText(temporaryPath, "UNRELATED");
                        replacementPath = temporaryPath;
                    }));

            Assert.Equal("ORIGINAL", File.ReadAllText(outputPath));
            Assert.NotNull(replacementPath);
            Assert.Equal("UNRELATED", File.ReadAllText(replacementPath));
            Assert.NotNull(movedOwnedPath);
            Assert.False(File.Exists(movedOwnedPath));
        }
        finally
        {
            if (Directory.Exists(testRoot))
            {
                Directory.Delete(testRoot, recursive: true);
            }
        }
    }

    [Fact]
    public void NonClosingStreamLeavesDurableFlushOwnershipWithCaller()
    {
        string path = Path.Combine(
            Path.GetTempPath(),
            $"dwg-probe-non-closing-{Guid.NewGuid():N}.tmp");
        try
        {
            using FileStream underlying = new(
                path,
                FileMode.CreateNew,
                FileAccess.ReadWrite,
                FileShare.Read);
            using (var wrapper = new NonClosingStream(underlying))
            {
                wrapper.Write([1, 2, 3]);
            }

            Assert.True(underlying.CanWrite);
            underlying.Flush(flushToDisk: true);
            Assert.Equal(3, underlying.Length);
        }
        finally
        {
            if (File.Exists(path))
            {
                File.Delete(path);
            }
        }
    }

    [Fact]
    public void ProbeCandidateCleanupFailurePreventsReportPublication()
    {
        string root = RepositoryRoot();
        string sourcePath = Path.Combine(
            root,
            "tests",
            "fixtures",
            "dwg",
            "export_sample.dwg");
        string testRoot = Path.Combine(
            Path.GetTempPath(),
            $"dwg-probe-locked-cleanup-{Guid.NewGuid():N}");
        string outputPath = Path.Combine(testRoot, "report.json");
        Directory.CreateDirectory(testRoot);
        FileStream? lockedCandidate = null;
        string? candidateRoot = null;
        try
        {
            CadIoException error = Assert.Throws<CadIoException>(
                () => DwgVersionProbe.Run(
                    sourcePath,
                    outputPath,
                    afterCandidateWrite: null,
                    beforeCleanup: rootPath =>
                    {
                        candidateRoot = rootPath;
                    },
                    afterOwnedHandlesClosed: rootPath =>
                    {
                        string candidate = Directory
                            .EnumerateFiles(rootPath, "*.dwg")
                            .First();
                        lockedCandidate = new FileStream(
                            candidate,
                            FileMode.Open,
                            FileAccess.Read,
                            FileShare.ReadWrite);
                    }));

            Assert.NotNull(lockedCandidate);
            Assert.NotNull(candidateRoot);
            Assert.Equal(
                "DWG_PROBE_CLEANUP_FAILED",
                error.Code);
            Assert.False(File.Exists(outputPath));
            Assert.Empty(Directory.EnumerateFileSystemEntries(
                testRoot,
                ".report.json.*.tmp"));
            Assert.True(Directory.Exists(candidateRoot));
            Assert.All(
                Directory.EnumerateFiles(candidateRoot, "*.dwg"),
                candidate => Assert.Equal(
                    0,
                    new FileInfo(candidate).Length));

            lockedCandidate.Dispose();
            lockedCandidate = null;
            Directory.Delete(candidateRoot, recursive: true);
            candidateRoot = null;
        }
        finally
        {
            lockedCandidate?.Dispose();
            if (
                candidateRoot is not null
                && Directory.Exists(candidateRoot))
            {
                Directory.Delete(candidateRoot, recursive: true);
            }
            Directory.Delete(testRoot, recursive: true);
        }
    }

    [Fact]
    public void ProbeCleanupRejectsAPathSwappedForgedReplacement()
    {
        string testRoot = Path.Combine(
            Path.GetTempPath(),
            $"dwg-probe-path-swap-{Guid.NewGuid():N}");
        string processTemp = Path.Combine(
            testRoot,
            "process-temp");
        string originalRoot = Path.Combine(
            processTemp,
            $"dwg-version-probe-{Guid.NewGuid():N}");
        string outputPath = Path.Combine(testRoot, "report.json");
        string movedRoot = Path.Combine(
            processTemp,
            $"owned.moved.{Guid.NewGuid():N}");
        string ownerToken = "A".Repeat(64);
        Directory.CreateDirectory(originalRoot);
        File.WriteAllText(
            Path.Combine(
                originalRoot,
                DwgVersionProbe.OwnerMarkerName),
            ownerToken);
        foreach (
            string candidate in DwgVersionPolicy.CandidateVersions)
        {
            File.WriteAllText(
                Path.Combine(originalRoot, $"{candidate}.dwg"),
                $"OWNED:{candidate}");
        }
        Directory.Move(originalRoot, movedRoot);
        var candidateHandles = Directory
            .EnumerateFiles(movedRoot, "*.dwg")
            .Select(path => new FileStream(
                path,
                FileMode.Open,
                FileAccess.ReadWrite,
                FileShare.ReadWrite | FileShare.Delete))
            .ToList();
        FileStream? lockedCandidate = null;
        try
        {
            lockedCandidate = new FileStream(
                Path.Combine(movedRoot, "AC1032.dwg"),
                FileMode.Open,
                FileAccess.Read,
                FileShare.ReadWrite);
            Directory.CreateDirectory(originalRoot);
            File.WriteAllText(
                Path.Combine(
                    originalRoot,
                    DwgVersionProbe.OwnerMarkerName),
                "FORGED");
            File.WriteAllText(
                Path.Combine(originalRoot, "unrelated.txt"),
                "UNRELATED");

            CadIoException error = Assert.Throws<CadIoException>(
                () => DwgVersionProbe.CleanupCandidateRoot(
                    originalRoot,
                    ownerToken,
                    candidateHandles));

            Assert.Equal(
                "DWG_PROBE_CLEANUP_FAILED",
                error.Code);
            Assert.False(File.Exists(outputPath));
            Assert.Equal(
                "UNRELATED",
                File.ReadAllText(Path.Combine(
                    originalRoot,
                    "unrelated.txt")));
            Assert.Equal(
                "FORGED",
                File.ReadAllText(Path.Combine(
                    originalRoot,
                    DwgVersionProbe.OwnerMarkerName)));
            Assert.Empty(Directory.EnumerateFileSystemEntries(
                testRoot,
                ".report.json.*.tmp"));
            Assert.All(
                Directory.EnumerateFiles(movedRoot, "*.dwg"),
                candidate => Assert.Equal(
                    0,
                    new FileInfo(candidate).Length));

            lockedCandidate.Dispose();
            lockedCandidate = null;
        }
        finally
        {
            lockedCandidate?.Dispose();
            foreach (FileStream handle in candidateHandles)
            {
                handle.Dispose();
            }
            if (Directory.Exists(movedRoot))
            {
                Directory.Delete(movedRoot, recursive: true);
            }
            Directory.Delete(testRoot, recursive: true);
        }
    }

    public static IEnumerable<object[]> InvalidManifestJson()
    {
        yield return [ManifestJson(verifiedVersion: null)];
        yield return [ManifestJson(
            verifiedVersion: "AC1032",
            rootExtra: ",\"unknown\":true")];
        yield return [ManifestJson(
            verifiedVersion: "AC1032",
            entryExtra: ",\"unknown\":true")];
        yield return [ManifestJson(
            verifiedVersion: "AC1032",
            duplicateRootKey: true)];
        yield return [ManifestJson(
            verifiedVersion: "AC1032",
            versions: [
                "AC1014",
                "AC1015",
                "AC1018",
                "AC1024",
                "AC1027",
                "AC1027"
            ])];
        yield return [ManifestJson(
            verifiedVersion: "AC1032",
            versions: ExpectedCandidates[..^1])];
        yield return [ManifestJson(
            verifiedVersion: "AC1032",
            versions: [
                "AC1014",
                "AC1015",
                "AC1018",
                "AC1024",
                "AC1027",
                "AC9999"
            ])];
        yield return [ManifestJson(
            verifiedVersion: "AC1032",
            verifiedHash: "a".Repeat(64))];
        yield return [ManifestJson(
            verifiedVersion: "AC1032",
            unverifiedHash: "A".Repeat(64))];
    }

    private static string ManifestJson(
        string? verifiedVersion,
        IReadOnlyList<string>? versions = null,
        string verifiedHash = "",
        string unverifiedHash = "",
        string rootExtra = "",
        string entryExtra = "",
        bool duplicateRootKey = false)
    {
        versions ??= ExpectedCandidates;
        string fixtureHash = string.IsNullOrEmpty(verifiedHash)
            ? "A".Repeat(64)
            : verifiedHash;
        string entries = string.Join(
            ",",
            versions.Select(version =>
            {
                bool verified = version == verifiedVersion;
                string probeHash = verified
                    ? fixtureHash
                    : unverifiedHash;
                string invariantHash = verified
                    ? "B".Repeat(64)
                    : unverifiedHash;
                return $$"""
                {
                  "version":"{{version}}",
                  "probeFixtureSha256":"{{probeHash}}",
                  "verified":{{verified.ToString().ToLowerInvariant()}},
                  "invariantSha256":"{{invariantHash}}"{{entryExtra}}
                }
                """;
            }));
        string duplicate = duplicateRootKey
            ? ",\"schemaVersion\":\"dwg-roundtrip-policy/v1\""
            : "";
        return $$"""
        {
          "schemaVersion":"dwg-roundtrip-policy/v1"{{duplicate}},
          "candidates":[{{entries}}]{{rootExtra}}
        }
        """;
    }

    private static string RepositoryRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (
            directory is not null
            && (!Directory.Exists(
                    Path.Combine(directory.FullName, "apps"))
                || !Directory.Exists(
                    Path.Combine(directory.FullName, "tests"))))
        {
            directory = directory.Parent;
        }
        return directory?.FullName
            ?? throw new InvalidOperationException(
                "Repository root was not found.");
    }

    private static string Sha256(string path)
    {
        using FileStream stream = File.OpenRead(path);
        return Convert.ToHexString(SHA256.HashData(stream));
    }

    private static async Task<ProcessResult> RunProbeHost(
        string repositoryRoot,
        string sourcePath,
        string outputPath,
        string processTemp)
    {
        using Process process = StartProbeHost(
            repositoryRoot,
            sourcePath,
            outputPath,
            processTemp);
        string stdout = await process.StandardOutput.ReadToEndAsync();
        string stderr = await process.StandardError.ReadToEndAsync();
        await process.WaitForExitAsync();
        return new ProcessResult(process.ExitCode, stdout, stderr);
    }

    private static Process StartProbeHost(
        string repositoryRoot,
        string sourcePath,
        string outputPath,
        string processTemp)
    {
        string host = Path.Combine(
            repositoryRoot,
            "modules",
            "cad-io-acadsharp",
            "src",
            "DwgIntelligence.CadIo.Host",
            "bin",
            "Debug",
            "net9.0",
            "DwgIntelligence.CadIo.Host.dll");
        var start = new ProcessStartInfo("dotnet")
        {
            WorkingDirectory = repositoryRoot,
            RedirectStandardInput = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true
        };
        start.ArgumentList.Add(host);
        start.ArgumentList.Add("--probe-versions");
        start.ArgumentList.Add(sourcePath);
        start.ArgumentList.Add(outputPath);
        start.Environment["TEMP"] = processTemp;
        start.Environment["TMP"] = processTemp;
        Process process = Process.Start(start)!;
        process.StandardInput.Close();
        return process;
    }

    private sealed class PolicyFixture : IDisposable
    {
        public required string Root { get; init; }
        public required string ManifestPath { get; init; }

        public static PolicyFixture Create(
            string? verifiedVersion = null,
            string? json = null)
        {
            string root = Path.Combine(
                Path.GetTempPath(),
                $"dwg-policy-{Guid.NewGuid():N}");
            Directory.CreateDirectory(root);
            string manifestPath = Path.Combine(root, "manifest.json");
            File.WriteAllText(
                manifestPath,
                json ?? ManifestJson(verifiedVersion),
                new UTF8Encoding(false));
            return new PolicyFixture
            {
                Root = root,
                ManifestPath = manifestPath
            };
        }

        public void Dispose()
        {
            Directory.Delete(Root, recursive: true);
        }
    }
}

internal sealed record ProcessResult(
    int ExitCode,
    string Stdout,
    string Stderr);

internal static class StringTestExtensions
{
    public static string Repeat(this string value, int count)
    {
        return string.Concat(Enumerable.Repeat(value, count));
    }
}
