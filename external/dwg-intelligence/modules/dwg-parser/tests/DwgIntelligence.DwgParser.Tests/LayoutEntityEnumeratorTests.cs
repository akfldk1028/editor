using ACadSharp;
using ACadSharp.Entities;
using ACadSharp.Objects;
using ACadSharp.Tables;
using CSMath;
using Xunit;

namespace DwgIntelligence.DwgParser.Tests;

public sealed class LayoutEntityEnumeratorTests
{
    [Fact]
    public void EnumeratesModelAndPaperOwnersWithoutFlatteningDefinitions()
    {
        var document = new CadDocument();
        var modelLine = new Line(XYZ.Zero, new XYZ(10, 0, 0));
        document.Entities.Add(modelLine);

        var sheet = new Layout("A101");
        document.Layouts.Add(sheet);
        var paperLine = new Line(
            new XYZ(1, 1, 0),
            new XYZ(2, 2, 0));
        sheet.AssociatedBlock.Entities.Add(paperLine);

        var definition = new BlockRecord("DoorDefinition");
        var definitionCircle = new Circle { Radius = 3 };
        definition.Entities.Add(definitionCircle);
        document.BlockRecords.Add(definition);

        LayoutEnumerationResult result =
            LayoutEntityEnumerator.Enumerate(document);

        Assert.Contains(
            result.Entities,
            item =>
                ReferenceEquals(item.Entity, modelLine) &&
                item.Space == "model" &&
                item.Layout == "Model");
        Assert.Contains(
            result.Entities,
            item =>
                ReferenceEquals(item.Entity, paperLine) &&
                item.Space == "paper" &&
                item.Layout == "A101");
        Assert.DoesNotContain(
            result.Entities,
            item => ReferenceEquals(item.Entity, definitionCircle));
    }

    [Fact]
    public void KeepsFirstStableIdentityAndReportsDuplicate()
    {
        var first = new LocatedCadEntity(
            new Line(),
            "model",
            "Model",
            0);
        var second = new LocatedCadEntity(
            new Circle(),
            "paper",
            "A101",
            1);

        LayoutEnumerationResult result = LayoutEntityEnumerator.Deduplicate(
            [first, second],
            _ => "h:AA");

        Assert.Equal([first], result.Entities);
        Assert.Equal(1, result.DuplicateHandles["h:AA"]);
    }
}
