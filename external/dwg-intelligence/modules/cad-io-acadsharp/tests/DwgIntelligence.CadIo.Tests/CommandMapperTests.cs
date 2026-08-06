using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using ACadSharp;
using ACadSharp.Entities;
using ACadSharp.IO;
using ACadSharp.Tables;
using Xunit;

namespace DwgIntelligence.CadIo.Tests;

public sealed class CommandMapperTests
{
    private const string Transaction1 = "11111111-1111-4111-8111-111111111111";
    private const string Transaction2 = "22222222-2222-4222-8222-222222222222";
    private const string CopyCommand = "33333333-3333-4333-8333-333333333333";
    private const string CopyCommand2 = "44444444-4444-4444-8444-444444444444";
    private const string CopyId =
        $"copy:{Transaction1}:{CopyCommand}:0";
    private const string CopyId2 =
        $"copy:{Transaction2}:{CopyCommand2}:1";

    [Fact]
    public void WritesAndReopensTwoOrderedTransactionsWithoutChangingSource()
    {
        using var fixture = TemporaryFixture.Create();
        string sourceHash = Sha256(fixture.SourcePath);
        CadIoRequest request = CadIoRequest.Parse(ValidRequestJson(
            fixture.SourcePath,
            fixture.OutputPath));

        CadIoSuccessResponse result = CadFileWriter.Write(request);

        Assert.Equal(sourceHash, Sha256(fixture.SourcePath));
        Assert.Equal("dxf", result.Format);
        Assert.Equal("AC1032", result.Version);
        Assert.Equal(5, result.EntityCount);
        Assert.Equal(2, result.CopiedHandleMap.Count);
        Assert.Equal(
            new[] { CopyId, CopyId2 },
            result.CopiedHandleMap.Keys.Order().ToArray());
        string[] copiedHandles =
            result.CopiedHandleMap.Values.ToArray();
        Assert.All(
            copiedHandles,
            handle => Assert.Matches(
                "^[1-9A-F][0-9A-F]{0,15}$",
                handle));
        Assert.Equal(2, copiedHandles.Distinct().Count());
        Assert.DoesNotContain("10", copiedHandles);
        Assert.DoesNotContain("11", copiedHandles);

        CadDocument output = DxfReader.Read(fixture.OutputPath);
        Assert.Equal(ACadVersion.AC1032, output.Header.Version);
        Layer review = Assert.Single(
            output.Layers,
            layer => layer.Name == "REVIEW-FINAL");
        Assert.Equal(5, review.Color.Index);
        Assert.False(review.IsOn);
        Assert.True(review.Flags.HasFlag(LayerFlags.Frozen));
        Assert.True(review.Flags.HasFlag(LayerFlags.Locked));

        TextEntity text = Assert.IsType<TextEntity>(
            output.GetCadObject(0x30));
        Assert.Equal("ROOM 101A", text.Value);
        Assert.Equal("ANNOTATION", text.Layer.Name);

        Line moved = Assert.IsType<Line>(output.GetCadObject(0x10));
        Assert.Equal([5d, 6d, 0d], [
            moved.StartPoint.X,
            moved.StartPoint.Y,
            moved.StartPoint.Z
        ]);
        Assert.Null(output.GetCadObject(0x11));

        LwPolyline polylineCopy = Assert.IsType<LwPolyline>(
            output.GetCadObject(Convert.ToUInt64(
                result.CopiedHandleMap[CopyId],
                16)));
        Assert.Equal(10d, polylineCopy.Vertices[0].Location.X);
        Assert.Equal(20d, polylineCopy.Vertices[0].Location.Y);
        LwPolyline polylineCopy2 = Assert.IsType<LwPolyline>(
            output.GetCadObject(Convert.ToUInt64(
                result.CopiedHandleMap[CopyId2],
                16)));
        Assert.Equal(-2d, polylineCopy2.Vertices[0].Location.X);
        Assert.Equal(3d, polylineCopy2.Vertices[0].Location.Y);
    }

    [Fact]
    public void RejectsCaseInsensitiveLayerRenameCollisionWithoutOutput()
    {
        using var fixture = TemporaryFixture.Create();
        string sourceHash = Sha256(fixture.SourcePath);
        string json = RequestJson(
            fixture.SourcePath,
            fixture.OutputPath,
            [
                Transaction(Transaction1, 0, 1, [
                    new
                    {
                        kind = "layer.create",
                        layerId = "layer:created:review",
                        name = "Review",
                        color = 4
                    },
                    new
                    {
                        kind = "text.replace",
                        handle = "30",
                        value = "MUST ROLL BACK"
                    },
                    new
                    {
                        kind = "layer.update",
                        layerId = "layer:imported:QS1URVhU",
                        name = "review"
                    }
                ])
            ]);

        CadIoException error = Assert.Throws<CadIoException>(
            () => CadFileWriter.Write(CadIoRequest.Parse(json)));

        Assert.Equal("CAD_LAYER_EXISTS", error.Code);
        Assert.False(File.Exists(fixture.OutputPath));
        Assert.Equal(sourceHash, Sha256(fixture.SourcePath));
        CadDocument source = DxfReader.Read(fixture.SourcePath);
        Assert.Equal(
            "ROOM 101",
            Assert.IsType<TextEntity>(source.GetCadObject(0x30)).Value);
    }

    [Fact]
    public void AllowsCaseOnlyRenameOfTheSameLayer()
    {
        using var fixture = TemporaryFixture.Create();
        string json = RequestJson(
            fixture.SourcePath,
            fixture.OutputPath,
            [
                Transaction(Transaction1, 0, 1, [
                    new
                    {
                        kind = "layer.update",
                        layerId = "layer:imported:QS1URVhU",
                        name = "a-text"
                    }
                ])
            ]);

        CadFileWriter.Write(CadIoRequest.Parse(json));

        CadDocument output = DxfReader.Read(fixture.OutputPath);
        Assert.Contains(output.Layers, layer => layer.Name == "a-text");
    }

    [Fact]
    public void ValidUlongHandleMissingFromDrawingReturnsControlledError()
    {
        using var fixture = TemporaryFixture.Create();
        string json = RequestJson(
            fixture.SourcePath,
            fixture.OutputPath,
            [
                Transaction(Transaction1, 0, 1, [
                    new
                    {
                        kind = "entity.delete",
                        handles = new[] { "FFFFFFFFFFFFFFFF" }
                    }
                ])
            ]);

        CadIoException error = Assert.Throws<CadIoException>(
            () => CadFileWriter.Write(CadIoRequest.Parse(json)));

        Assert.Equal("CAD_ENTITY_NOT_FOUND", error.Code);
        Assert.False(File.Exists(fixture.OutputPath));
    }

    [Theory]
    [InlineData("1")]
    [InlineData("FFFFFFFFFFFFFFFF")]
    public void StrictParserAcceptsCanonicalUlongHandles(string handle)
    {
        CadIoRequest request = CadIoRequest.Parse(RequestJson(
            "C:\\a.dxf",
            "C:\\b.dxf",
            [
                Transaction(Transaction1, 0, 1, [
                    new
                    {
                        kind = "entity.delete",
                        handles = new[] { handle }
                    }
                ])
            ]));

        EntityDeleteCommand command = Assert.IsType<EntityDeleteCommand>(
            Assert.Single(Assert.Single(request.Lineage).Commands));
        Assert.Equal(handle, Assert.Single(command.Handles));
    }

    [Theory]
    [InlineData("0")]
    [InlineData("0000000000000001")]
    [InlineData("10000000000000000")]
    [InlineData("abcdef")]
    [InlineData("+1")]
    [InlineData(" 1")]
    [InlineData("1 ")]
    public void StrictParserRejectsNonCanonicalOrOverflowHandles(
        string handle)
    {
        string json = RequestJson(
            "C:\\a.dxf",
            "C:\\b.dxf",
            [
                Transaction(Transaction1, 0, 1, [
                    new
                    {
                        kind = "entity.delete",
                        handles = new[] { handle }
                    }
                ])
            ]);

        CadIoException error = Assert.Throws<CadIoException>(
            () => CadIoRequest.Parse(json));

        Assert.Equal("CAD_REQUEST_INVALID", error.Code);
    }

    [Fact]
    public void StrictParserRejectsZeroCopySourceHandle()
    {
        string json = RequestJson(
            "C:\\a.dxf",
            "C:\\b.dxf",
            [
                Transaction(Transaction1, 0, 1, [
                    new
                    {
                        kind = "entity.copy",
                        sourceHandles = new[] { "0" },
                        temporaryIds = new[] { CopyId },
                        delta = new[] { 0d, 0d, 0d }
                    }
                ])
            ]);

        CadIoException error = Assert.Throws<CadIoException>(
            () => CadIoRequest.Parse(json));

        Assert.Equal("CAD_REQUEST_INVALID", error.Code);
    }

    [Fact]
    public void MapperRejectsAnUnassignedCopiedEntityHandle()
    {
        using var fixture = TemporaryFixture.Create();
        CadDocument document = DxfReader.Read(fixture.SourcePath);
        Entity source = Assert.IsType<LwPolyline>(
            document.GetCadObject(0x11));
        BlockRecord owner = Assert.IsType<BlockRecord>(source.Owner);
        EventHandler<CollectionChangedEventArgs> resetCopyHandle =
            (_, args) =>
            {
                if (!ReferenceEquals(args.Item, source))
                {
                    typeof(CadObject)
                        .GetProperty(nameof(CadObject.Handle))!
                        .SetValue(args.Item, 0UL);
                }
            };
        owner.Entities.OnAdd += resetCopyHandle;
        try
        {
            CadIoException error = Assert.Throws<CadIoException>(
                () => CommandMapper.Apply(
                    document,
                    [
                        new CadIoWriteTransaction(
                            Transaction1,
                            0,
                            1,
                            [
                                new EntityCopyCommand(
                                    ["11"],
                                    [CopyId],
                                    new CadPoint3(0, 0, 0))
                            ])
                    ]));

            Assert.Equal("CAD_COPY_MAPPING_INVALID", error.Code);
        }
        finally
        {
            owner.Entities.OnAdd -= resetCopyHandle;
        }
    }

    [Theory]
    [InlineData("0")]
    [InlineData("2147483647")]
    public void StrictParserAcceptsCanonicalTemporaryIdIndexes(
        string index)
    {
        string id = $"copy:{Transaction1}:{CopyCommand}:{index}";
        CadIoRequest request = CadIoRequest.Parse(RequestJson(
            "C:\\a.dxf",
            "C:\\b.dxf",
            [
                Transaction(Transaction1, 0, 1, [
                    new
                    {
                        kind = "entity.copy",
                        sourceHandles = new[] { "10" },
                        temporaryIds = new[] { id },
                        delta = new[] { 0d, 0d, 0d }
                    }
                ])
            ]));

        EntityCopyCommand command = Assert.IsType<EntityCopyCommand>(
            Assert.Single(Assert.Single(request.Lineage).Commands));
        Assert.Equal(id, Assert.Single(command.TemporaryIds));
    }

    [Theory]
    [InlineData("01")]
    [InlineData("+1")]
    [InlineData(" 1")]
    [InlineData("1 ")]
    [InlineData("2147483648")]
    public void StrictParserRejectsNonCanonicalTemporaryIdIndexes(
        string index)
    {
        string id = $"copy:{Transaction1}:{CopyCommand}:{index}";
        string json = RequestJson(
            "C:\\a.dxf",
            "C:\\b.dxf",
            [
                Transaction(Transaction1, 0, 1, [
                    new
                    {
                        kind = "entity.copy",
                        sourceHandles = new[] { "10" },
                        temporaryIds = new[] { id },
                        delta = new[] { 0d, 0d, 0d }
                    }
                ])
            ]);

        CadIoException error = Assert.Throws<CadIoException>(
            () => CadIoRequest.Parse(json));

        Assert.Equal("CAD_REQUEST_INVALID", error.Code);
    }

    [Fact]
    public void RejectsMissingHandleAndLeavesNoPartialOutput()
    {
        using var fixture = TemporaryFixture.Create();
        string sourceHash = Sha256(fixture.SourcePath);
        string json = RequestJson(
            fixture.SourcePath,
            fixture.OutputPath,
            [
                Transaction(Transaction1, 0, 1, [
                    new
                    {
                        kind = "text.replace",
                        handle = "30",
                        value = "MUST ROLL BACK"
                    },
                    new
                    {
                        kind = "entity.delete",
                        handles = new[] { "FFFF" }
                    }
                ])
            ]);

        CadIoException error = Assert.Throws<CadIoException>(
            () => CadFileWriter.Write(CadIoRequest.Parse(json)));

        Assert.Equal("CAD_ENTITY_NOT_FOUND", error.Code);
        Assert.False(File.Exists(fixture.OutputPath));
        Assert.Equal(sourceHash, Sha256(fixture.SourcePath));
        CadDocument source = DxfReader.Read(fixture.SourcePath);
        Assert.Equal(
            "ROOM 101",
            Assert.IsType<TextEntity>(source.GetCadObject(0x30)).Value);
    }

    [Fact]
    public void RejectsUnsupportedEntityBeforeWriting()
    {
        using var fixture = TemporaryFixture.Create();
        string json = RequestJson(
            fixture.SourcePath,
            fixture.OutputPath,
            [
                Transaction(Transaction1, 0, 1, [
                    new
                    {
                        kind = "entity.move",
                        handles = new[] { "20" },
                        delta = new[] { 1d, 0d, 0d }
                    }
                ])
            ]);

        CadIoException error = Assert.Throws<CadIoException>(
            () => CadFileWriter.Write(CadIoRequest.Parse(json)));

        Assert.Equal("CAD_ENTITY_UNSUPPORTED", error.Code);
        Assert.False(File.Exists(fixture.OutputPath));
    }

    [Theory]
    [MemberData(nameof(InvalidJsonRequests))]
    public void StrictParserRejectsMalformedWireRequests(
        string json,
        string expectedCode)
    {
        CadIoException error = Assert.Throws<CadIoException>(
            () => CadIoRequest.Parse(json));

        Assert.Equal(expectedCode, error.Code);
    }

    [Fact]
    public void RejectsNonContiguousLineageBeforeReadingSource()
    {
        string json = RequestJson(
            "C:\\does-not-exist\\source.dxf",
            "C:\\does-not-exist\\output.dxf",
            [
                Transaction(Transaction1, 0, 1, [
                    new
                    {
                        kind = "entity.delete",
                        handles = new[] { "10" }
                    }
                ]),
                Transaction(Transaction2, 2, 3, [
                    new
                    {
                        kind = "entity.delete",
                        handles = new[] { "11" }
                    }
                ])
            ]);

        CadIoException error = Assert.Throws<CadIoException>(
            () => CadIoRequest.Parse(json));

        Assert.Equal("CAD_LINEAGE_INVALID", error.Code);
    }

    [Fact]
    public async Task HostBoundsGenericFailureOutputAndEmitsOneResponse()
    {
        string root = RepositoryRoot();
        string host = Path.Combine(
            root,
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
            WorkingDirectory = root,
            RedirectStandardInput = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true
        };
        start.ArgumentList.Add(host);
        using Process process = Process.Start(start)!;
        try
        {
            await process.StandardInput.WriteAsync(
                Encoding.UTF8.GetString(
                    new byte[CadIoRequest.MaxJsonBytes + 1]));
            process.StandardInput.Close();
        }
        catch (IOException)
        {
            // The bounded host may close stdin as soon as it observes overflow.
        }
        string stdout = await process.StandardOutput.ReadToEndAsync();
        string stderr = await process.StandardError.ReadToEndAsync();
        await process.WaitForExitAsync();

        Assert.NotEqual(0, process.ExitCode);
        Assert.Single(
            stdout.Split(
                Environment.NewLine,
                StringSplitOptions.RemoveEmptyEntries));
        using JsonDocument response = JsonDocument.Parse(stdout);
        Assert.Equal(
            "error",
            response.RootElement.GetProperty("status").GetString());
        Assert.InRange(
            Encoding.UTF8.GetByteCount(stdout),
            1,
            CadIoRequest.MaxJsonBytes);
        Assert.InRange(Encoding.UTF8.GetByteCount(stderr), 1, 256);
        Assert.Equal("CAD I/O request failed.", stderr.Trim());
        Assert.DoesNotContain("sourcePath", stdout + stderr);
    }

    public static IEnumerable<object[]> InvalidJsonRequests()
    {
        yield return ["{", "CAD_REQUEST_INVALID"];
        yield return [
            """
            {
              "schemaVersion":"cad-io/v1",
              "schemaVersion":"cad-io/v1",
              "operation":"write-copy",
              "sourcePath":"C:\\a.dxf",
              "temporaryOutputPath":"C:\\b.dxf",
              "format":"dxf",
              "version":"AC1032",
              "lineage":[]
            }
            """,
            "CAD_REQUEST_INVALID"
        ];
        yield return [
            """
            {
              "schemaVersion":"cad-io/v1",
              "operation":"write-copy",
              "sourcePath":"C:\\a.dxf",
              "temporaryOutputPath":"C:\\b.dxf",
              "format":"dxf",
              "version":"AC1032",
              "lineage":[],
              "unknown":true
            }
            """,
            "CAD_REQUEST_INVALID"
        ];
        yield return [
            $$"""
            {
              "schemaVersion":"cad-io/v1",
              "operation":"write-copy",
              "sourcePath":"C:\\a.dxf",
              "temporaryOutputPath":"C:\\b.dxf",
              "format":"dxf",
              "version":"AC1032",
              "lineage":[{
                "transactionId":"{{Transaction1}}",
                "beforeRevision":0,
                "afterRevision":1,
                "commands":[{
                  "kind":"entity.move",
                  "handles":["10"],
                  "delta":[1e9999,0,0]
                }]
              }]
            }
            """,
            "CAD_REQUEST_INVALID"
        ];
        yield return [
            RequestJson(
                "C:\\a.dxf",
                "C:\\b.dxf",
                [
                    Transaction(Transaction1, 0, 1, [
                        new
                        {
                            kind = "entity.delete",
                            handles = new[] { "10", "10" }
                        }
                    ])
                ]),
            "CAD_REQUEST_INVALID"
        ];
        yield return [
            RequestJson(
                "C:\\a.dxf",
                "C:\\b.dxf",
                [
                    Transaction(Transaction1, 0, 1, [
                        new
                        {
                            kind = "entity.copy",
                            sourceHandles = new[] { "10", "11" },
                            temporaryIds = new[] { CopyId, CopyId },
                            delta = new[] { 0d, 0d, 0d }
                        }
                    ])
                ]),
            "CAD_REQUEST_INVALID"
        ];
        yield return [
            RequestJson(
                "C:\\a.dxf",
                "C:\\b.dxf",
                [
                    Transaction(
                        Transaction1,
                        0,
                        1,
                        Enumerable.Range(0, 10_001)
                            .Select(index => (object)new
                            {
                                kind = "entity.delete",
                                handles = new[]
                                {
                                    (index + 1).ToString("X")
                                }
                            })
                            .ToArray())
                ]),
            "CAD_REQUEST_LIMIT"
        ];
        yield return [
            new string(' ', CadIoRequest.MaxJsonBytes + 1),
            "CAD_REQUEST_LIMIT"
        ];
    }

    private static string ValidRequestJson(
        string sourcePath,
        string outputPath)
    {
        return RequestJson(
            sourcePath,
            outputPath,
            [
                Transaction(Transaction1, 0, 1, [
                    new
                    {
                        kind = "layer.create",
                        layerId = "layer:created:review",
                        name = "REVIEW",
                        color = 4
                    },
                    new
                    {
                        kind = "layer.update",
                        layerId = "layer:imported:QS1URVhU",
                        name = "ANNOTATION",
                        color = 6,
                        visible = true,
                        frozen = false,
                        locked = false
                    },
                    new
                    {
                        kind = "text.replace",
                        handle = "30",
                        value = "ROOM 101A"
                    },
                    new
                    {
                        kind = "entity.move",
                        handles = new[] { "10" },
                        delta = new[] { 5d, 6d, 0d }
                    },
                    new
                    {
                        kind = "entity.copy",
                        sourceHandles = new[] { "11" },
                        temporaryIds = new[] { CopyId },
                        delta = new[] { 10d, 20d, 0d }
                    }
                ]),
                Transaction(Transaction2, 1, 2, [
                    new
                    {
                        kind = "entity.copy",
                        sourceHandles = new[] { "11" },
                        temporaryIds = new[] { CopyId2 },
                        delta = new[] { -2d, 3d, 0d }
                    },
                    new
                    {
                        kind = "layer.update",
                        layerId = "layer:created:review",
                        name = "REVIEW-FINAL",
                        color = 5,
                        visible = false,
                        frozen = true,
                        locked = true
                    },
                    new
                    {
                        kind = "entity.delete",
                        handles = new[] { "11" }
                    }
                ])
            ]);
    }

    private static object Transaction(
        string transactionId,
        int beforeRevision,
        int afterRevision,
        object[] commands)
    {
        return new
        {
            transactionId,
            beforeRevision,
            afterRevision,
            commands
        };
    }

    private static string RequestJson(
        string sourcePath,
        string outputPath,
        object[] lineage)
    {
        return JsonSerializer.Serialize(new
        {
            schemaVersion = "cad-io/v1",
            operation = "write-copy",
            sourcePath,
            temporaryOutputPath = outputPath,
            format = "dxf",
            version = "AC1032",
            lineage
        });
    }

    private static string Sha256(string path)
    {
        using FileStream stream = File.OpenRead(path);
        return Convert.ToHexString(SHA256.HashData(stream));
    }

    private static string RepositoryRoot()
    {
        DirectoryInfo? directory =
            new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null)
        {
            if (
                Directory.Exists(
                    Path.Combine(directory.FullName, "apps"))
                && Directory.Exists(
                    Path.Combine(directory.FullName, "packages")))
            {
                return directory.FullName;
            }
            directory = directory.Parent;
        }
        throw new InvalidOperationException("Repository root not found.");
    }

    private sealed class TemporaryFixture : IDisposable
    {
        private readonly string directory;

        public string SourcePath { get; }

        public string OutputPath { get; }

        private TemporaryFixture(
            string directory,
            string sourcePath,
            string outputPath)
        {
            this.directory = directory;
            SourcePath = sourcePath;
            OutputPath = outputPath;
        }

        public static TemporaryFixture Create()
        {
            string directory = Path.Combine(
                Path.GetTempPath(),
                $"click-around-cad-io-{Guid.NewGuid():N}");
            Directory.CreateDirectory(directory);
            string source = Path.Combine(directory, "source.dxf");
            File.Copy(
                Path.Combine(
                    AppContext.BaseDirectory,
                    "Fixtures",
                    "minimal-architectural.dxf"),
                source);
            return new TemporaryFixture(
                directory,
                source,
                Path.Combine(directory, "output.dxf"));
        }

        public void Dispose()
        {
            Directory.Delete(directory, recursive: true);
        }
    }
}
