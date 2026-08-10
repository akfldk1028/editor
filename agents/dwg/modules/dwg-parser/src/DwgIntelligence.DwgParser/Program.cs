using DwgIntelligence.CadIo;

namespace DwgIntelligence.DwgParser;

public static class Program
{
    public static int Main(string[] args)
    {
        if (args.Length != 2 || args[0] != "index")
        {
            Console.Error.WriteLine("Usage: dwg-parser index <path-to-dwg>");
            return 2;
        }

        try
        {
            string path = Path.GetFullPath(args[1]);
            if (!File.Exists(path))
            {
                throw new FileNotFoundException("DWG file not found.", path);
            }
            string extension = Path.GetExtension(path);
            if (
                !extension.Equals(".dwg", StringComparison.OrdinalIgnoreCase)
                && !extension.Equals(".dxf", StringComparison.OrdinalIgnoreCase))
            {
                throw new ArgumentException(
                    "Input must use the .dwg or .dxf extension.",
                    nameof(args));
            }

            CadIndex index = DwgIndexBuilder.Build(path);
            string json = System.Text.Json.JsonSerializer.Serialize(
                index,
                new System.Text.Json.JsonSerializerOptions
                {
                    PropertyNamingPolicy = System.Text.Json.JsonNamingPolicy.CamelCase
                });
            Console.Out.Write(json);
            return 0;
        }
        catch (Exception exception)
        {
            Console.Error.WriteLine(exception.Message);
            return 2;
        }
    }
}
