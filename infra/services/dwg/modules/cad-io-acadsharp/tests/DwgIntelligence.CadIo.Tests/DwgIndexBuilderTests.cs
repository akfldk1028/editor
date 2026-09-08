using ACadSharp.Entities;
using CSMath;
using Xunit;

namespace DwgIntelligence.CadIo.Tests;

public sealed class DwgIndexBuilderTests
{
    [Fact]
    public void NonZNormalHatchPreservesItsWorldZExtent()
    {
        var hatch = new FixedBoundingBoxHatch
        {
            Normal = XYZ.AxisX
        };
        CadBoundingBox bbox = BuildBoundingBox(hatch);

        Assert.Equal([1d, 2d, 3d], bbox.Min);
        Assert.Equal([4d, 5d, 6d], bbox.Max);
    }

    [Fact]
    public void PositiveZNormalHatchUsesItsElevationForWorldZ()
    {
        var hatch = new FixedBoundingBoxHatch
        {
            Normal = XYZ.AxisZ,
            Elevation = 9d
        };
        CadBoundingBox bbox = BuildBoundingBox(hatch);

        Assert.Equal([1d, 2d, 9d], bbox.Min);
        Assert.Equal([4d, 5d, 9d], bbox.Max);
    }

    [Fact]
    public void NegativeZNormalHatchUsesItsElevationInWorldCoordinates()
    {
        var hatch = new FixedBoundingBoxHatch
        {
            Normal = new XYZ(0d, 0d, -1d),
            Elevation = 9d
        };
        CadBoundingBox bbox = BuildBoundingBox(hatch);

        Assert.Equal([1d, 2d, -9d], bbox.Min);
        Assert.Equal([4d, 5d, -9d], bbox.Max);
    }

    private static CadBoundingBox BuildBoundingBox(Hatch hatch)
    {
        var warnings = new List<string>();
        var unsupported = new Dictionary<(string Type, string Reason), int>();
        return Assert.IsType<CadBoundingBox>(DwgIndexBuilder.GetBoundingBox(
            hatch,
            "HATCH",
            warnings,
            unsupported));
    }

    private sealed class FixedBoundingBoxHatch : Hatch
    {
        public override BoundingBox GetBoundingBox()
        {
            return new BoundingBox(
                new XYZ(1d, 2d, 3d),
                new XYZ(4d, 5d, 6d));
        }
    }
}
