using ACadSharp.Entities;
using ACadSharp.Tables;
using Xunit;

namespace DwgIntelligence.DwgParser.Tests;

public sealed class InsertAttributeExtractorTests
{
    [Fact]
    public void ExtractsSingleAndMultilineAttributeValues()
    {
        var insert = new Insert(new BlockRecord("TitleBlock"));
        insert.Attributes.Add(new AttributeEntity
        {
            Tag = "SHEET",
            Value = "A101"
        });
        insert.Attributes.Add(new AttributeEntity
        {
            Tag = "TITLE",
            Value = "fallback",
            MText = new MText { Value = "Ground\\PFloor" }
        });

        InsertAttributeResult result =
            InsertAttributeExtractor.Extract(insert);

        Assert.Equal("A101", result.Attributes["SHEET"]);
        Assert.Equal(
            $"Ground{Environment.NewLine}Floor",
            result.Attributes["TITLE"]);
        Assert.Empty(result.Warnings);
    }

    [Fact]
    public void KeepsFirstDuplicateAndRejectsEmptyTags()
    {
        var insert = new Insert(new BlockRecord("TitleBlock"));
        insert.Attributes.Add(new AttributeEntity
        {
            Tag = "SHEET",
            Value = "A101"
        });
        insert.Attributes.Add(new AttributeEntity
        {
            Tag = "SHEET",
            Value = "A102"
        });
        insert.Attributes.Add(new AttributeEntity
        {
            Tag = " ",
            Value = "ignored"
        });

        InsertAttributeResult result =
            InsertAttributeExtractor.Extract(insert);

        Assert.Equal("A101", result.Attributes["SHEET"]);
        Assert.False(result.Attributes.ContainsKey(" "));
        Assert.Equal(
            [
                "duplicate-insert-attribute:SHEET",
                "empty-insert-attribute-tag"
            ],
            result.Warnings);
    }
}
