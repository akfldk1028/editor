using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using ACadSharp;
using ACadSharp.IO;
using DwgIntelligence.CadIo;

public static class DwgVersionProbe
{
    private const int MaxWarnings = 16;
    private const int MaxWarningCharacters = 120;
    internal const string OwnerMarkerName =
        ".dwg-version-probe-owner";
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        WriteIndented = true
    };

    public static void Run(string sourcePath, string outputPath)
    {
        Run(
            sourcePath,
            outputPath,
            afterCandidateWrite: null,
            beforeCleanup: null);
    }

    internal static void Run(
        string sourcePath,
        string outputPath,
        Action<string>? afterCandidateWrite,
        Action<string>? beforeCleanup,
        Action<string>? afterDeleteIdentityVerified = null,
        Action<string>? beforeReportTempCleanup = null,
        Action<string>? afterOwnedHandlesClosed = null)
    {
        string source = Path.GetFullPath(sourcePath);
        string output = Path.GetFullPath(outputPath);
        if (
            !File.Exists(source)
            || !string.Equals(
                Path.GetExtension(source),
                ".dwg",
                StringComparison.OrdinalIgnoreCase)
            || string.Equals(
                source,
                output,
                StringComparison.OrdinalIgnoreCase))
        {
            throw new CadIoException("DWG_PROBE_INVALID");
        }
        string? outputDirectory = Path.GetDirectoryName(output);
        if (string.IsNullOrEmpty(outputDirectory))
        {
            throw new CadIoException("DWG_PROBE_INVALID");
        }
        Directory.CreateDirectory(outputDirectory);

        string sourceSha256 = Sha256File(source);
        CadIndex sourceIndex;
        string sourceInvariant;
        try
        {
            sourceIndex = DwgIndexBuilder.Build(source);
            sourceInvariant =
                DwgRoundTripInvariant.ComputeSha256(sourceIndex);
        }
        catch (Exception exception)
        {
            throw new CadIoException("DWG_PROBE_SOURCE_INVALID", exception);
        }

        string tempRoot = Path.Combine(
            Path.GetTempPath(),
            $"dwg-version-probe-{Guid.NewGuid():N}");
        Directory.CreateDirectory(tempRoot);
        string ownerToken = Convert.ToHexString(
            RandomNumberGenerator.GetBytes(32));
        var ownedFiles = new List<OwnedProbeFile>();
        var results = new List<DwgVersionProbeResult>();
        try
        {
            ownedFiles.Add(CreateOwnedFile(
                tempRoot,
                OwnerMarkerName,
                Encoding.UTF8.GetBytes(ownerToken)));
            foreach (
                string candidate in DwgVersionPolicy.CandidateVersions)
            {
                results.Add(ProbeCandidate(
                    source,
                    sourceSha256,
                    sourceInvariant,
                    candidate,
                    tempRoot,
                    ownedFiles,
                    afterCandidateWrite));
            }
            if (Sha256File(source) != sourceSha256)
            {
                throw new CadIoException("DWG_PROBE_SOURCE_CHANGED");
            }
        }
        finally
        {
            beforeCleanup?.Invoke(tempRoot);
            CleanupCandidateRoot(
                tempRoot,
                ownerToken,
                ownedFiles,
                afterDeleteIdentityVerified,
                afterOwnedHandlesClosed);
        }

        var report = new DwgVersionProbeReport(
            "dwg-version-probe/v1",
            sourceSha256,
            sourceInvariant,
            results.AsReadOnly());
        string json = JsonSerializer.Serialize(report, JsonOptions);
        if (
            Encoding.UTF8.GetByteCount(json)
            > CadIoRequest.MaxJsonBytes)
        {
            throw new CadIoException("DWG_PROBE_RESULT_LIMIT");
        }

        string temporaryOutput = Path.Combine(
            outputDirectory,
            $".{Path.GetFileName(output)}.{Guid.NewGuid():N}.tmp");
        FileStream? temporaryHandle = null;
        FileIdentity temporaryIdentity = default;
        bool published = false;
        try
        {
            temporaryHandle =
                ExactFileHandleDeletion.CreateNewReadWrite(
                    temporaryOutput);
            temporaryIdentity =
                ExactFileHandleDeletion.GetIdentity(
                    temporaryHandle.SafeFileHandle);
            byte[] reportBytes = new UTF8Encoding(false).GetBytes(
                json + Environment.NewLine);
            temporaryHandle.Write(reportBytes);
            temporaryHandle.Flush(flushToDisk: true);
            File.Move(temporaryOutput, output);
            if (!PathMatchesIdentity(output, temporaryIdentity))
            {
                throw CleanupFailed();
            }
            published = true;
        }
        finally
        {
            try
            {
                if (!published && temporaryHandle is not null)
                {
                    beforeReportTempCleanup?.Invoke(temporaryOutput);
                    ExactFileHandleDeletion.DeleteOpenHandle(
                        temporaryHandle,
                        temporaryIdentity);
                }
            }
            finally
            {
                temporaryHandle?.Dispose();
            }
        }
    }

    internal static void CleanupCandidateRoot(
        string originalPath,
        string ownerToken,
        ICollection<FileStream> candidateHandles)
    {
        var ownedFiles = new List<OwnedProbeFile>();
        try
        {
            foreach (FileStream handle in candidateHandles)
            {
                ownedFiles.Add(new OwnedProbeFile(
                    Path.GetFileName(handle.Name),
                    handle,
                    ExactFileHandleDeletion.GetIdentity(
                        handle.SafeFileHandle),
                    IsCandidate: true));
            }
            string markerPath = Path.Combine(
                originalPath,
                OwnerMarkerName);
            if (File.Exists(markerPath))
            {
                FileStream markerHandle = OpenOwnedFile(markerPath);
                ownedFiles.Add(new OwnedProbeFile(
                    OwnerMarkerName,
                    markerHandle,
                    ExactFileHandleDeletion.GetIdentity(
                        markerHandle.SafeFileHandle),
                    IsCandidate: false));
            }
            CleanupCandidateRoot(
                originalPath,
                ownerToken,
                ownedFiles,
                afterDeleteIdentityVerified: null,
                afterOwnedHandlesClosed: null);
        }
        finally
        {
            candidateHandles.Clear();
        }
    }

    private static void CleanupCandidateRoot(
        string originalPath,
        string ownerToken,
        ICollection<OwnedProbeFile> ownedFiles,
        Action<string>? afterDeleteIdentityVerified,
        Action<string>? afterOwnedHandlesClosed)
    {
        Exception? closeFailure = NeutralizeAndClose(ownedFiles);
        if (closeFailure is not null)
        {
            throw CleanupFailed(closeFailure);
        }
        afterOwnedHandlesClosed?.Invoke(originalPath);
        string quarantinePath = Path.Combine(
            Path.GetDirectoryName(originalPath)
                ?? Path.GetTempPath(),
            $"dwg-version-probe-quarantine-{Guid.NewGuid():N}");
        try
        {
            Directory.Move(originalPath, quarantinePath);
        }
        catch (Exception exception)
        {
            throw CleanupFailed(exception);
        }

        if (!MarkerMatches(quarantinePath, ownerToken))
        {
            TryRestoreUnrelatedReplacement(
                quarantinePath,
                originalPath);
            throw CleanupFailed();
        }

        if (!OwnedChildrenMatch(quarantinePath, ownedFiles))
        {
            TryRestoreUnrelatedReplacement(
                quarantinePath,
                originalPath);
            throw CleanupFailed();
        }

        try
        {
            foreach (
                OwnedProbeFile owned
                in ownedFiles.Where(file => file.IsCandidate))
            {
                DeleteOwnedFile(
                    quarantinePath,
                    owned,
                    afterDeleteIdentityVerified);
            }
            OwnedProbeFile marker = ownedFiles.Single(
                file => !file.IsCandidate);
            DeleteOwnedFile(
                quarantinePath,
                marker,
                afterDeleteIdentityVerified);
            Directory.Delete(quarantinePath, recursive: false);
        }
        catch (Exception exception)
        {
            TryRestoreUnrelatedReplacement(
                quarantinePath,
                originalPath);
            throw CleanupFailed(exception);
        }
    }

    private static OwnedProbeFile CreateOwnedFile(
        string root,
        string name,
        byte[]? initialBytes = null)
    {
        string path = Path.Combine(root, name);
        FileStream handle = CreateOwnedStream(path);
        try
        {
            if (initialBytes is not null)
            {
                handle.Write(initialBytes);
                handle.Flush(flushToDisk: true);
                handle.Position = 0;
            }
            return new OwnedProbeFile(
                name,
                handle,
                ExactFileHandleDeletion.GetIdentity(
                    handle.SafeFileHandle),
                name != OwnerMarkerName);
        }
        catch
        {
            handle.Dispose();
            throw;
        }
    }

    private static bool MarkerMatches(
        string root,
        string expectedToken)
    {
        string path = Path.Combine(root, OwnerMarkerName);
        try
        {
            if (
                File.GetAttributes(path)
                    .HasFlag(FileAttributes.ReparsePoint))
            {
                return false;
            }
            byte[] actual = File.ReadAllBytes(path);
            byte[] expected = Encoding.UTF8.GetBytes(expectedToken);
            return actual.Length == expected.Length
                && CryptographicOperations.FixedTimeEquals(
                    actual,
                    expected);
        }
        catch
        {
            return false;
        }
    }

    private static void TryRestoreUnrelatedReplacement(
        string quarantinePath,
        string originalPath)
    {
        try
        {
            if (
                !Directory.Exists(originalPath)
                && !File.Exists(originalPath))
            {
                Directory.Move(quarantinePath, originalPath);
            }
        }
        catch
        {
            // The unowned replacement remains untouched in quarantine.
        }
    }

    private static bool OwnedChildrenMatch(
        string root,
        ICollection<OwnedProbeFile> ownedFiles)
    {
        string[] actualNames = Directory
            .EnumerateFileSystemEntries(root)
            .Select(Path.GetFileName)
            .OrderBy(name => name, StringComparer.Ordinal)
            .ToArray()!;
        string[] expectedNames = ownedFiles
            .Select(file => file.Name)
            .OrderBy(name => name, StringComparer.Ordinal)
            .ToArray();
        if (!actualNames.SequenceEqual(
            expectedNames,
            StringComparer.Ordinal))
        {
            return false;
        }
        return ownedFiles.All(owned =>
            PathMatchesIdentity(
                Path.Combine(root, owned.Name),
                owned.Identity));
    }

    private static Exception? NeutralizeAndClose(
        ICollection<OwnedProbeFile> ownedFiles)
    {
        Exception? firstFailure = null;
        foreach (OwnedProbeFile owned in ownedFiles)
        {
            try
            {
                if (owned.IsCandidate)
                {
                    owned.Handle.Position = 0;
                    owned.Handle.SetLength(0);
                    owned.Handle.Flush(flushToDisk: true);
                }
            }
            catch (Exception exception)
            {
                firstFailure ??= exception;
            }
            finally
            {
                try
                {
                    owned.Handle.Dispose();
                }
                catch (Exception exception)
                {
                    firstFailure ??= exception;
                }
            }
        }
        return firstFailure;
    }

    private static void DeleteOwnedFile(
        string root,
        OwnedProbeFile owned,
        Action<string>? afterIdentityVerified)
    {
        string path = Path.Combine(root, owned.Name);
        ExactFileHandleDeletion.DeleteVerifiedPath(
            path,
            owned.Identity,
            afterIdentityVerified);
    }

    private static CadIoException CleanupFailed(
        Exception? exception = null)
    {
        return exception is null
            ? new CadIoException("DWG_PROBE_CLEANUP_FAILED")
            : new CadIoException(
                "DWG_PROBE_CLEANUP_FAILED",
                exception);
    }

    private static DwgVersionProbeResult ProbeCandidate(
        string source,
        string sourceSha256,
        string sourceInvariant,
        string candidate,
        string tempRoot,
        ICollection<OwnedProbeFile> ownedFiles,
        Action<string>? afterCandidateWrite)
    {
        var warnings = new List<string>();
        string observedInvariant = "";
        bool verified = false;
        string candidatePath = Path.Combine(
            tempRoot,
            $"{candidate}.dwg");
        OwnedProbeFile owned = CreateOwnedFile(
            tempRoot,
            $"{candidate}.dwg");
        ownedFiles.Add(owned);
        try
        {
            if (!Enum.TryParse(candidate, out ACadVersion version))
            {
                warnings.Add("candidate-version-invalid");
            }
            else
            {
                CadDocument document = DwgReader.Read(source);
                document.Header.Version = version;
                document.UpdateDxfClasses(reset: false);
                using FileStream writerHandle =
                    OpenOwnedFile(candidatePath);
                if (
                    ExactFileHandleDeletion.GetIdentity(
                        writerHandle.SafeFileHandle)
                    != owned.Identity)
                {
                    writerHandle.Dispose();
                    warnings.Add("candidate-identity-mismatch");
                    return new DwgVersionProbeResult(
                        candidate,
                        sourceSha256,
                        sourceInvariant,
                        observedInvariant,
                        false,
                        BoundWarnings(warnings));
                }
                writerHandle.Position = 0;
                writerHandle.SetLength(0);
                DwgWriter.Write(
                    new NonClosingStream(writerHandle),
                    document);
                writerHandle.Flush(flushToDisk: true);
                afterCandidateWrite?.Invoke(candidatePath);
                if (!PathMatchesIdentity(candidatePath, owned.Identity))
                {
                    warnings.Add("candidate-identity-mismatch");
                    return new DwgVersionProbeResult(
                        candidate,
                        sourceSha256,
                        sourceInvariant,
                        observedInvariant,
                        false,
                        BoundWarnings(warnings));
                }
                using FileStream readerHandle =
                    OpenOwnedFile(candidatePath);
                if (
                    ExactFileHandleDeletion.GetIdentity(
                        readerHandle.SafeFileHandle)
                    != owned.Identity)
                {
                    warnings.Add("candidate-identity-mismatch");
                    return new DwgVersionProbeResult(
                        candidate,
                        sourceSha256,
                        sourceInvariant,
                        observedInvariant,
                        false,
                        BoundWarnings(warnings));
                }
                CadIndex reopened = DwgIndexBuilder.Build(
                    readerHandle,
                    candidatePath);
                observedInvariant =
                    DwgRoundTripInvariant.ComputeSha256(reopened);
                if (reopened.Drawing.FileVersion != candidate)
                {
                    warnings.Add("reopened-version-mismatch");
                }
                if (observedInvariant != sourceInvariant)
                {
                    warnings.Add("roundtrip-invariant-mismatch");
                }
                verified = warnings.Count == 0;
            }
        }
        catch (Exception exception)
        {
            warnings.Add(
                $"candidate-failed:{exception.GetType().Name}");
        }
        return new DwgVersionProbeResult(
            candidate,
            sourceSha256,
            sourceInvariant,
            observedInvariant,
            verified,
            BoundWarnings(warnings));
    }

    private static bool PathMatchesIdentity(
        string path,
        FileIdentity expected)
    {
        try
        {
            using FileStream handle = OpenOwnedFile(path);
            return ExactFileHandleDeletion.GetIdentity(
                handle.SafeFileHandle)
                == expected;
        }
        catch
        {
            return false;
        }
    }

    private static FileStream CreateOwnedStream(string path)
    {
        return ExactFileHandleDeletion.CreateNewReadWrite(path);
    }

    private static FileStream OpenOwnedFile(string path)
    {
        return new FileStream(
            path,
            FileMode.Open,
            FileAccess.ReadWrite,
            FileShare.ReadWrite | FileShare.Delete);
    }

    private sealed record OwnedProbeFile(
        string Name,
        FileStream Handle,
        FileIdentity Identity,
        bool IsCandidate);

    private static IReadOnlyList<string> BoundWarnings(
        IEnumerable<string> warnings)
    {
        return Array.AsReadOnly(
            warnings
                .Take(MaxWarnings)
                .Select(warning => warning.Length <= MaxWarningCharacters
                    ? warning
                    : warning[..MaxWarningCharacters])
                .ToArray());
    }

    private static string Sha256File(string path)
    {
        using FileStream stream = File.OpenRead(path);
        return Convert.ToHexString(SHA256.HashData(stream));
    }
}

public sealed record DwgVersionProbeReport(
    string SchemaVersion,
    string ProbeFixtureSha256,
    string InvariantSha256,
    IReadOnlyList<DwgVersionProbeResult> Candidates);

public sealed record DwgVersionProbeResult(
    string Version,
    string ProbeFixtureSha256,
    string InvariantSha256,
    string ObservedInvariantSha256,
    bool Verified,
    IReadOnlyList<string> Warnings);
