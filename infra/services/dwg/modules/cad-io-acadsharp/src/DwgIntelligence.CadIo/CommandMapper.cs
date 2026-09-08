using System.Text;
using ACadSharp;
using ACadSharp.Entities;
using ACadSharp.Tables;
using CSMath;

namespace DwgIntelligence.CadIo;

internal static class CommandMapper
{
    private static readonly HashSet<Type> EditableTypes =
    [
        typeof(Line),
        typeof(Circle),
        typeof(Arc),
        typeof(LwPolyline)
    ];

    public static CommandMappingResult Apply(
        CadDocument document,
        IReadOnlyList<CadIoWriteTransaction> lineage)
    {
        var copiedHandles = new Dictionary<string, string>(
            StringComparer.Ordinal);
        var layers = document.Layers.ToDictionary(
            layer => ImportedLayerId(layer.Name),
            layer => layer,
            StringComparer.Ordinal);

        foreach (CadIoWriteTransaction transaction in lineage)
        {
            foreach (CadIoWriteCommand command in transaction.Commands)
            {
                ApplyCommand(
                    document,
                    command,
                    layers,
                    copiedHandles);
            }
        }
        int expectedMappings = lineage.Sum(
            transaction => transaction.Commands.Sum(
                command => command is EntityCopyCommand copy
                    ? copy.TemporaryIds.Count
                    : 0));
        if (copiedHandles.Count != expectedMappings)
        {
            throw new CadIoException("CAD_COPY_MAPPING_INVALID");
        }
        return new CommandMappingResult(copiedHandles, []);
    }

    private static void ApplyCommand(
        CadDocument document,
        CadIoWriteCommand command,
        IDictionary<string, Layer> layers,
        IDictionary<string, string> copiedHandles)
    {
        switch (command)
        {
            case LayerCreateCommand create:
                CreateLayer(document, create, layers);
                return;
            case LayerUpdateCommand update:
                UpdateLayer(document, update, layers);
                return;
            case TextReplaceCommand replace:
                ReplaceText(document, replace);
                return;
            case EntityMoveCommand move:
                foreach (string handle in move.Handles)
                {
                    EditableEntity(document, handle).ApplyTranslation(
                        Point(move.Delta));
                }
                return;
            case EntityCopyCommand copy:
                CopyEntities(document, copy, copiedHandles);
                return;
            case EntityDeleteCommand delete:
                foreach (string handle in delete.Handles)
                {
                    Entity entity = EditableEntity(document, handle);
                    if (
                        entity.Owner is not BlockRecord owner
                        || !owner.Entities.Remove(entity))
                    {
                        throw new CadIoException(
                            "CAD_ENTITY_DELETE_FAILED");
                    }
                }
                return;
            default:
                throw new CadIoException("CAD_REQUEST_INVALID");
        }
    }

    private static void CreateLayer(
        CadDocument document,
        LayerCreateCommand command,
        IDictionary<string, Layer> layers)
    {
        if (
            layers.ContainsKey(command.LayerId)
            || document.Layers.Any(layer =>
                StringComparer.OrdinalIgnoreCase.Equals(
                    layer.Name,
                    command.Name)))
        {
            throw new CadIoException("CAD_LAYER_EXISTS");
        }
        var layer = new Layer(command.Name)
        {
            Color = new Color((short)command.Color)
        };
        document.Layers.Add(layer);
        layers.Add(command.LayerId, layer);
    }

    private static void UpdateLayer(
        CadDocument document,
        LayerUpdateCommand command,
        IDictionary<string, Layer> layers)
    {
        if (!layers.TryGetValue(command.LayerId, out Layer? layer))
        {
            throw new CadIoException("CAD_LAYER_NOT_FOUND");
        }
        if (command.Name is not null)
        {
            if (layers.Values.Any(candidate =>
                !ReferenceEquals(candidate, layer)
                && StringComparer.OrdinalIgnoreCase.Equals(
                    candidate.Name,
                    command.Name)))
            {
                throw new CadIoException("CAD_LAYER_EXISTS");
            }
            RenameLayer(document, layer, command.Name);
        }
        if (command.Color is not null)
        {
            layer.Color = new Color((short)command.Color.Value);
        }
        if (command.Visible is not null)
        {
            layer.IsOn = command.Visible.Value;
        }
        if (command.Frozen is not null)
        {
            layer.Flags = SetFlag(
                layer.Flags,
                LayerFlags.Frozen,
                command.Frozen.Value);
        }
        if (command.Locked is not null)
        {
            layer.Flags = SetFlag(
                layer.Flags,
                LayerFlags.Locked,
                command.Locked.Value);
        }
    }

    private static void RenameLayer(
        CadDocument document,
        Layer layer,
        string name)
    {
        if (StringComparer.Ordinal.Equals(layer.Name, name))
        {
            return;
        }
        if (!StringComparer.OrdinalIgnoreCase.Equals(layer.Name, name))
        {
            layer.Name = name;
            return;
        }

        string previousName = layer.Name;
        if (!ReferenceEquals(
            document.Layers.Remove(previousName),
            layer))
        {
            throw new CadIoException("CAD_LAYER_RENAME_FAILED");
        }
        try
        {
            layer.Name = name;
            document.Layers.Add(layer);
        }
        catch (Exception exception)
        {
            throw new CadIoException(
                "CAD_LAYER_RENAME_FAILED",
                exception);
        }
    }

    private static void ReplaceText(
        CadDocument document,
        TextReplaceCommand command)
    {
        Entity entity = FindEntity(document, command.Handle);
        switch (entity)
        {
            case TextEntity text:
                text.Value = command.Value;
                return;
            case MText text:
                text.Value = command.Value;
                return;
            default:
                throw new CadIoException("CAD_ENTITY_UNSUPPORTED");
        }
    }

    private static void CopyEntities(
        CadDocument document,
        EntityCopyCommand command,
        IDictionary<string, string> copiedHandles)
    {
        for (int index = 0; index < command.SourceHandles.Count; index++)
        {
            Entity source = EditableEntity(
                document,
                command.SourceHandles[index]);
            if (source.Owner is not BlockRecord owner)
            {
                throw new CadIoException("CAD_ENTITY_UNSUPPORTED");
            }
            Entity copy = (Entity)source.Clone();
            copy.ApplyTranslation(Point(command.Delta));
            owner.Entities.Add(copy);
            if (copy.Handle == 0)
            {
                throw new CadIoException("CAD_COPY_MAPPING_INVALID");
            }
            string handle = copy.Handle.ToString("X");
            string temporaryId = command.TemporaryIds[index];
            if (
                copiedHandles.ContainsKey(temporaryId)
                || copiedHandles.Values.Contains(
                    handle,
                    StringComparer.Ordinal))
            {
                throw new CadIoException("CAD_COPY_MAPPING_INVALID");
            }
            copiedHandles.Add(temporaryId, handle);
        }
    }

    private static Entity EditableEntity(
        CadDocument document,
        string handle)
    {
        Entity entity = FindEntity(document, handle);
        if (!EditableTypes.Contains(entity.GetType()))
        {
            throw new CadIoException("CAD_ENTITY_UNSUPPORTED");
        }
        return entity;
    }

    private static Entity FindEntity(
        CadDocument document,
        string handle)
    {
        ulong parsed = Convert.ToUInt64(handle, 16);
        return document.GetCadObject<Entity>(parsed)
            ?? throw new CadIoException("CAD_ENTITY_NOT_FOUND");
    }

    private static LayerFlags SetFlag(
        LayerFlags flags,
        LayerFlags flag,
        bool enabled)
    {
        return enabled ? flags | flag : flags & ~flag;
    }

    private static XYZ Point(CadPoint3 point)
    {
        return new XYZ(point.X, point.Y, point.Z);
    }

    private static string ImportedLayerId(string name)
    {
        return $"layer:imported:{Convert.ToBase64String(
                Encoding.UTF8.GetBytes(name))
            .TrimEnd('=')
            .Replace('+', '-')
            .Replace('/', '_')}";
    }
}

internal sealed record CommandMappingResult(
    IReadOnlyDictionary<string, string> CopiedHandleMap,
    IReadOnlyList<string> Warnings);
