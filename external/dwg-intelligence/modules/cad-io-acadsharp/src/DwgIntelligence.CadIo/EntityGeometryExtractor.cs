using ACadSharp.Entities;
using CSMath;
using CadPoint = ACadSharp.Entities.Point;

namespace DwgIntelligence.CadIo;

public static class EntityGeometryExtractor
{
    private const double NormalTolerance = 1e-9;

    public static GeometryExtraction Extract(
        Entity entity,
        CadBoundingBox? bbox)
    {
        string type = EntityType(entity);
        try
        {
            return entity switch
            {
                Arc arc => ExtractArc(arc, bbox, type),
                Circle circle => ExtractCircle(circle, bbox, type),
                Line line => ExtractLine(line, bbox, type),
                LwPolyline polyline => ExtractPolyline(polyline, bbox, type),
                CadPoint point => ExtractPoint(point, bbox, type),
                TextEntity text => ExtractText(text, bbox, type),
                MText text => ExtractMText(text, bbox, type),
                Insert insert => ExtractInsert(insert, bbox, type),
                _ => Fallback(type, bbox, $"geometry-fallback:{type}")
            };
        }
        catch
        {
            return Invalid(type, bbox);
        }
    }

    private static GeometryExtraction ExtractLine(
        Line line,
        CadBoundingBox? bbox,
        string type)
    {
        if (!IsPlanar(line.Normal))
        {
            return NonPlanar(type, bbox);
        }
        if (!IsFinite(line.StartPoint) || !IsFinite(line.EndPoint))
        {
            return Invalid(type, bbox);
        }
        return Result(new LineGeometry(
            "line",
            Point(line.StartPoint),
            Point(line.EndPoint)));
    }

    private static GeometryExtraction ExtractCircle(
        Circle circle,
        CadBoundingBox? bbox,
        string type)
    {
        if (!IsPlanar(circle.Normal))
        {
            return NonPlanar(type, bbox);
        }
        if (!IsFinite(circle.Center) ||
            !IsPositiveFinite(circle.Radius) ||
            !IsFinite(circle.Normal))
        {
            return Invalid(type, bbox);
        }
        return Result(new CircleGeometry(
            "circle",
            Point(circle.Center),
            circle.Radius,
            Point(circle.Normal)));
    }

    private static GeometryExtraction ExtractArc(
        Arc arc,
        CadBoundingBox? bbox,
        string type)
    {
        if (!IsPlanar(arc.Normal))
        {
            return NonPlanar(type, bbox);
        }
        if (!IsFinite(arc.Center) ||
            !IsPositiveFinite(arc.Radius) ||
            !double.IsFinite(arc.StartAngle) ||
            !double.IsFinite(arc.EndAngle) ||
            !IsFinite(arc.Normal))
        {
            return Invalid(type, bbox);
        }
        return Result(new ArcGeometry(
            "arc",
            Point(arc.Center),
            arc.Radius,
            arc.StartAngle,
            arc.EndAngle,
            Point(arc.Normal)));
    }

    private static GeometryExtraction ExtractPolyline(
        LwPolyline polyline,
        CadBoundingBox? bbox,
        string type)
    {
        if (!IsPlanar(polyline.Normal))
        {
            return NonPlanar(type, bbox);
        }
        if (!double.IsFinite(polyline.Elevation) ||
            !IsFinite(polyline.Normal))
        {
            return Invalid(type, bbox);
        }

        var vertices = new List<LwPolylineVertexGeometry>();
        foreach (LwPolyline.Vertex vertex in polyline.Vertices)
        {
            if (!double.IsFinite(vertex.Location.X) ||
                !double.IsFinite(vertex.Location.Y) ||
                !double.IsFinite(vertex.Bulge) ||
                !double.IsFinite(vertex.StartWidth) ||
                !double.IsFinite(vertex.EndWidth))
            {
                return Invalid(type, bbox);
            }
            vertices.Add(new LwPolylineVertexGeometry(
                [vertex.Location.X, vertex.Location.Y, polyline.Elevation],
                vertex.Bulge,
                vertex.StartWidth,
                vertex.EndWidth));
        }

        return Result(new LwPolylineGeometry(
            "lwpolyline",
            vertices,
            polyline.IsClosed,
            polyline.Elevation,
            Point(polyline.Normal)));
    }

    private static GeometryExtraction ExtractPoint(
        CadPoint point,
        CadBoundingBox? bbox,
        string type)
    {
        if (!IsPlanar(point.Normal))
        {
            return NonPlanar(type, bbox);
        }
        if (!IsFinite(point.Location))
        {
            return Invalid(type, bbox);
        }
        return Result(new PointGeometry("point", Point(point.Location)));
    }

    private static GeometryExtraction ExtractText(
        TextEntity text,
        CadBoundingBox? bbox,
        string type)
    {
        if (!IsPlanar(text.Normal))
        {
            return NonPlanar(type, bbox);
        }
        if (!IsFinite(text.InsertPoint) ||
            !IsFinite(text.AlignmentPoint) ||
            !IsPositiveFinite(text.Height) ||
            !double.IsFinite(text.Rotation) ||
            !double.IsFinite(text.WidthFactor))
        {
            return Invalid(type, bbox);
        }
        return Result(new TextGeometry(
            "text",
            Point(text.InsertPoint),
            Point(text.AlignmentPoint),
            text.Height,
            text.Rotation,
            text.WidthFactor));
    }

    private static GeometryExtraction ExtractMText(
        MText text,
        CadBoundingBox? bbox,
        string type)
    {
        if (!IsPlanar(text.Normal))
        {
            return NonPlanar(type, bbox);
        }
        if (!IsFinite(text.InsertPoint) ||
            !IsFinite(text.AlignmentPoint) ||
            !IsPositiveFinite(text.Height) ||
            !double.IsFinite(text.Rotation) ||
            !double.IsFinite(text.RectangleWidth))
        {
            return Invalid(type, bbox);
        }
        return Result(new TextGeometry(
            "text",
            Point(text.InsertPoint),
            Point(text.AlignmentPoint),
            text.Height,
            text.Rotation,
            text.RectangleWidth > 0 ? text.RectangleWidth : null));
    }

    private static GeometryExtraction ExtractInsert(
        Insert insert,
        CadBoundingBox? bbox,
        string type)
    {
        if (!IsPlanar(insert.Normal))
        {
            return NonPlanar(type, bbox);
        }
        if (!IsFinite(insert.InsertPoint) ||
            !double.IsFinite(insert.Rotation) ||
            !double.IsFinite(insert.XScale) ||
            !double.IsFinite(insert.YScale) ||
            !double.IsFinite(insert.ZScale) ||
            !IsFinite(insert.Normal))
        {
            return Invalid(type, bbox);
        }
        return Result(new InsertGeometry(
            "insert",
            Point(insert.InsertPoint),
            insert.Rotation,
            [insert.XScale, insert.YScale, insert.ZScale],
            Point(insert.Normal)));
    }

    private static GeometryExtraction NonPlanar(
        string type,
        CadBoundingBox? bbox)
    {
        return Fallback(type, bbox, "non-planar-geometry");
    }

    private static GeometryExtraction Invalid(
        string type,
        CadBoundingBox? bbox)
    {
        string reason = $"geometry-invalid:{type}";
        if (bbox is not null)
        {
            return new GeometryExtraction(
                new BboxGeometry("bbox", reason),
                [reason]);
        }
        return new GeometryExtraction(
            new UnavailableGeometry("unavailable", reason),
            [reason]);
    }

    private static GeometryExtraction Fallback(
        string type,
        CadBoundingBox? bbox,
        string reason)
    {
        if (bbox is not null)
        {
            return new GeometryExtraction(
                new BboxGeometry("bbox", reason),
                [reason]);
        }
        return new GeometryExtraction(
            new UnavailableGeometry("unavailable", reason),
            [reason]);
    }

    private static GeometryExtraction Result(CadEntityGeometry geometry)
    {
        return new GeometryExtraction(geometry, []);
    }

    private static bool IsPlanar(XYZ normal)
    {
        return
            IsFinite(normal) &&
            Math.Abs(normal.X) <= NormalTolerance &&
            Math.Abs(normal.Y) <= NormalTolerance &&
            Math.Abs(Math.Abs(normal.Z) - 1) <= NormalTolerance;
    }

    private static bool IsFinite(XYZ point)
    {
        return
            double.IsFinite(point.X) &&
            double.IsFinite(point.Y) &&
            double.IsFinite(point.Z);
    }

    private static bool IsPositiveFinite(double value)
    {
        return double.IsFinite(value) && value > 0;
    }

    private static double[] Point(XYZ point)
    {
        return [point.X, point.Y, point.Z];
    }

    private static string EntityType(Entity entity)
    {
        return string.IsNullOrWhiteSpace(entity.ObjectName)
            ? entity.GetType().Name.ToUpperInvariant()
            : entity.ObjectName;
    }
}
