using System.Text.Json.Serialization;

namespace DwgIntelligence.CadIo;

[JsonPolymorphic]
[JsonDerivedType(typeof(LineGeometry))]
[JsonDerivedType(typeof(CircleGeometry))]
[JsonDerivedType(typeof(ArcGeometry))]
[JsonDerivedType(typeof(LwPolylineGeometry))]
[JsonDerivedType(typeof(PointGeometry))]
[JsonDerivedType(typeof(TextGeometry))]
[JsonDerivedType(typeof(InsertGeometry))]
[JsonDerivedType(typeof(BboxGeometry))]
[JsonDerivedType(typeof(UnavailableGeometry))]
public abstract record CadEntityGeometry(string Kind);

public sealed record LineGeometry(
    string Kind,
    double[] Start,
    double[] End) : CadEntityGeometry(Kind);

public sealed record CircleGeometry(
    string Kind,
    double[] Center,
    double Radius,
    double[] Normal) : CadEntityGeometry(Kind);

public sealed record ArcGeometry(
    string Kind,
    double[] Center,
    double Radius,
    double StartAngle,
    double EndAngle,
    double[] Normal) : CadEntityGeometry(Kind);

public sealed record LwPolylineVertexGeometry(
    double[] Point,
    double Bulge,
    double StartWidth,
    double EndWidth);

public sealed record LwPolylineGeometry(
    string Kind,
    IReadOnlyList<LwPolylineVertexGeometry> Vertices,
    bool Closed,
    double Elevation,
    double[] Normal) : CadEntityGeometry(Kind);

public sealed record PointGeometry(
    string Kind,
    double[] Position) : CadEntityGeometry(Kind);

public sealed record TextGeometry(
    string Kind,
    double[] InsertionPoint,
    double[]? AlignmentPoint,
    double Height,
    double Rotation,
    double? Width) : CadEntityGeometry(Kind);

public sealed record InsertGeometry(
    string Kind,
    double[] InsertionPoint,
    double Rotation,
    double[] Scale,
    double[] Normal) : CadEntityGeometry(Kind);

public sealed record BboxGeometry(
    string Kind,
    string Reason) : CadEntityGeometry(Kind);

public sealed record UnavailableGeometry(
    string Kind,
    string Reason) : CadEntityGeometry(Kind);

public sealed record GeometryExtraction(
    CadEntityGeometry Geometry,
    IReadOnlyList<string> Warnings);
