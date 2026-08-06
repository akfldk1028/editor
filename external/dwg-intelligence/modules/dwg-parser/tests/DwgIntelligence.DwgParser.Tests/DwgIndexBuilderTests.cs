using System.Security.Cryptography;
using ACadSharp;
using ACadSharp.Tables;
using Xunit;

namespace DwgIntelligence.DwgParser.Tests;

public sealed class DwgIndexBuilderTests
{
    [Fact]
    public void BuildsV02GeometryFromRealDwgWithoutChangingSource()
    {
        string path = FixturePath("export_sample.dwg");
        string before = Sha256(path);

        CadIndex index = DwgIndexBuilder.Build(path);

        string after = Sha256(path);
        Assert.Equal("cad-index/v0.2", index.SchemaVersion);
        Assert.Equal("dwg", index.Source.Kind);
        Assert.Equal("acadsharp@3.6.35", index.Source.Parser);
        Assert.Equal(before, after);

        CadEntityItem line = Assert.Single(
            index.Entities,
            entity => entity.Handle == "23D");
        var lineGeometry = Assert.IsType<LineGeometry>(line.Geometry);
        double[][] endpoints = [lineGeometry.Start, lineGeometry.End];
        Assert.Contains(
            endpoints,
            point => point.SequenceEqual([25d, 50d, 0d]));
        Assert.Contains(
            endpoints,
            point => point.SequenceEqual([75d, 50d, 0d]));

        CadEntityItem circle = Assert.Single(
            index.Entities,
            entity => entity.Handle == "23C");
        var circleGeometry = Assert.IsType<CircleGeometry>(circle.Geometry);
        Assert.Equal(50, circleGeometry.Center[0], 10);
        Assert.Equal(50, circleGeometry.Center[1], 10);
        Assert.Equal(0, circleGeometry.Center[2], 10);
        Assert.Equal(50, circleGeometry.Radius, 10);

        CadEntityItem arc = Assert.Single(
            index.Entities,
            entity => entity.Handle == "23E");
        Assert.IsType<ArcGeometry>(arc.Geometry);

        CadEntityItem text = Assert.Single(
            index.Entities,
            entity => entity.Handle == "591");
        Assert.Equal("Hello", text.Text);
        Assert.IsType<TextGeometry>(text.Geometry);

        CadEntityItem insert = Assert.Single(
            index.Entities,
            entity => entity.Handle == "3B6");
        Assert.Equal("my_block", insert.BlockName);
        Assert.IsType<InsertGeometry>(insert.Geometry);

        CadEntityItem hatch = Assert.Single(
            index.Entities,
            entity => entity.Handle == "347");
        Assert.IsType<BboxGeometry>(hatch.Geometry);
        Assert.Contains("geometry-fallback:HATCH", hatch.Warnings);

        Assert.Equal(
            index.Entities.Count(entity => entity.Space == "model"),
            index.Summary.ModelSpaceCount);
        Assert.Equal(
            index.Entities.Count(entity => entity.Space == "paper"),
            index.Summary.PaperSpaceCount);
        Assert.Contains(
            index.Entities,
            entity => entity.Space == "paper" && entity.Type == "VIEWPORT");
    }

    [Fact]
    public void PublishesOfficialDwgMetadataAndLayerEvidence()
    {
        CadIndex index = DwgIndexBuilder.Build(FixturePath("export_sample.dwg"));

        Assert.NotNull(index.Drawing);
        Assert.Equal("AC1032", index.Drawing.FileVersion);
        Assert.Equal("Millimeters", index.Drawing.Units);
        Assert.Equal(
            [
                ("0", 7, false),
                ("Defpoints", 7, false),
                ("control", 90, false),
                ("out-margin", 1, false)
            ],
            index.Layers.Select(layer => (layer.Name, layer.Color, layer.Locked)));
    }

    [Fact]
    public void TrueColorLayerPublishesNullAciAndStableWarning()
    {
        var layer = new Layer("RGB-LAYER")
        {
            Color = Color.FromTrueColor(0x112233u)
        };
        var unsupported = new Dictionary<(string Type, string Reason), int>();

        CadLayerItem item = DwgIndexBuilder.CreateLayerItem(
            layer,
            [],
            unsupported);

        Assert.Null(item.Color);
        Assert.Equal(
            1,
            unsupported[("LAYER", "true-color-unsupported:RGB-LAYER")]);
    }

    private static string FixturePath(string name)
    {
        return Path.Combine(
            AppContext.BaseDirectory,
            "Fixtures",
            name);
    }

    private static string Sha256(string path)
    {
        using FileStream stream = File.OpenRead(path);
        return Convert.ToHexString(SHA256.HashData(stream));
    }
}
