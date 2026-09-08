using ACadSharp.Entities;
using CSMath;
using Xunit;

namespace DwgIntelligence.DwgParser.Tests;

public sealed class EntityGeometryExtractorTests
{
    [Fact]
    public void ExtractsLineCircleAndArcInRadians()
    {
        var line = new Line(new XYZ(1, 2, 0), new XYZ(8, 5, 0));
        var circle = new Circle
        {
            Center = new XYZ(5, 6, 0),
            Radius = 4
        };
        var arc = new Arc
        {
            Center = new XYZ(10, 20, 0),
            Radius = 5,
            StartAngle = Math.PI / 4,
            EndAngle = Math.PI
        };

        var lineGeometry = Assert.IsType<LineGeometry>(
            EntityGeometryExtractor.Extract(line, null).Geometry);
        Assert.Equal([1, 2, 0], lineGeometry.Start);
        Assert.Equal([8, 5, 0], lineGeometry.End);

        var circleGeometry = Assert.IsType<CircleGeometry>(
            EntityGeometryExtractor.Extract(circle, null).Geometry);
        Assert.Equal([5, 6, 0], circleGeometry.Center);
        Assert.Equal(4, circleGeometry.Radius);
        Assert.Equal([0, 0, 1], circleGeometry.Normal);

        var arcGeometry = Assert.IsType<ArcGeometry>(
            EntityGeometryExtractor.Extract(arc, null).Geometry);
        Assert.Equal(Math.PI / 4, arcGeometry.StartAngle, 12);
        Assert.Equal(Math.PI, arcGeometry.EndAngle, 12);
    }

    [Fact]
    public void PreservesLwPolylineBulgeWidthsClosureAndElevation()
    {
        var polyline = new LwPolyline
        {
            IsClosed = true,
            Elevation = 7
        };
        polyline.Vertices.Add(new LwPolyline.Vertex(0, 0)
        {
            Bulge = 0.5,
            StartWidth = 2,
            EndWidth = 3
        });
        polyline.Vertices.Add(new LwPolyline.Vertex(10, 0));

        var geometry = Assert.IsType<LwPolylineGeometry>(
            EntityGeometryExtractor.Extract(polyline, null).Geometry);

        Assert.True(geometry.Closed);
        Assert.Equal([0, 0, 7], geometry.Vertices[0].Point);
        Assert.Equal(0.5, geometry.Vertices[0].Bulge);
        Assert.Equal(2, geometry.Vertices[0].StartWidth);
        Assert.Equal(3, geometry.Vertices[0].EndWidth);
    }

    [Fact]
    public void ExtractsPointTextMTextAndInsertTransform()
    {
        var point = new Point(new XYZ(3, 4, 5));
        var text = new TextEntity
        {
            InsertPoint = new XYZ(1, 2, 0),
            AlignmentPoint = new XYZ(4, 5, 0),
            Height = 2,
            Rotation = Math.PI / 2,
            WidthFactor = 0.8,
            Value = "Hello"
        };
        var mtext = new MText
        {
            InsertPoint = new XYZ(6, 7, 0),
            AlignmentPoint = XYZ.AxisY,
            Height = 3,
            RectangleWidth = 12,
            Value = "Line1\\PLine2"
        };
        var insert = new Insert(new ACadSharp.Tables.BlockRecord("Door"))
        {
            InsertPoint = new XYZ(8, 9, 0),
            Rotation = Math.PI / 4,
            XScale = 2,
            YScale = 3,
            ZScale = 1
        };

        var pointGeometry = Assert.IsType<PointGeometry>(
            EntityGeometryExtractor.Extract(point, null).Geometry);
        Assert.Equal([3, 4, 5], pointGeometry.Position);

        var textGeometry = Assert.IsType<TextGeometry>(
            EntityGeometryExtractor.Extract(text, null).Geometry);
        Assert.Equal([1, 2, 0], textGeometry.InsertionPoint);
        Assert.NotNull(textGeometry.AlignmentPoint);
        Assert.Equal([4, 5, 0], textGeometry.AlignmentPoint);
        Assert.Equal(0.8, textGeometry.Width);

        var mtextGeometry = Assert.IsType<TextGeometry>(
            EntityGeometryExtractor.Extract(mtext, null).Geometry);
        Assert.Equal([6, 7, 0], mtextGeometry.InsertionPoint);
        Assert.Equal(12, mtextGeometry.Width);

        var insertGeometry = Assert.IsType<InsertGeometry>(
            EntityGeometryExtractor.Extract(insert, null).Geometry);
        Assert.Equal([8, 9, 0], insertGeometry.InsertionPoint);
        Assert.Equal([2, 3, 1], insertGeometry.Scale);
    }

    [Fact]
    public void UsesExplicitFallbackForUnsupportedAndNonPlanarGeometry()
    {
        var bbox = new CadBoundingBox([0, 0, 0], [4, 2, 0]);
        GeometryExtraction unsupported = EntityGeometryExtractor.Extract(
            new Ellipse(),
            bbox);

        Assert.IsType<BboxGeometry>(unsupported.Geometry);
        Assert.Contains("geometry-fallback:ELLIPSE", unsupported.Warnings);

        var line = new Line
        {
            StartPoint = XYZ.Zero,
            EndPoint = XYZ.AxisY,
            Normal = XYZ.AxisX
        };
        GeometryExtraction nonPlanar =
            EntityGeometryExtractor.Extract(line, bbox);

        Assert.IsType<BboxGeometry>(nonPlanar.Geometry);
        Assert.Contains("non-planar-geometry", nonPlanar.Warnings);
    }
}
