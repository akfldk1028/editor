using ACadSharp.Entities;

namespace DwgIntelligence.CadIo;

public sealed record InsertAttributeResult(
    IReadOnlyDictionary<string, string> Attributes,
    IReadOnlyList<string> Warnings);

public static class InsertAttributeExtractor
{
    public static InsertAttributeResult Extract(Insert insert)
    {
        var attributes = new Dictionary<string, string>(
            StringComparer.Ordinal);
        var warnings = new List<string>();

        foreach (AttributeEntity attribute in insert.Attributes)
        {
            string tag = attribute.Tag ?? string.Empty;
            if (string.IsNullOrWhiteSpace(tag))
            {
                warnings.Add("empty-insert-attribute-tag");
                continue;
            }

            string value = attribute.MText?.PlainText ?? attribute.Value;
            if (!attributes.TryAdd(tag, value))
            {
                warnings.Add($"duplicate-insert-attribute:{tag}");
            }
        }

        return new InsertAttributeResult(attributes, warnings);
    }
}
