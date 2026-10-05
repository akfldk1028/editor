"""Homogeneous 4x4 affine transforms for recursive MASS geometry programs.

Matrices are row-major and multiply column vectors. ``compose_matrix4`` takes
matrices in program order, so ``compose_matrix4(scale, translate)`` returns
``translate @ scale``.
"""

from __future__ import annotations

from math import cos, isfinite, radians, sin, sqrt
from typing import Any, Iterable, Sequence


Matrix4 = tuple[tuple[float, float, float, float], ...]


def identity_matrix4() -> Matrix4:
    return (
        (1.0, 0.0, 0.0, 0.0),
        (0.0, 1.0, 0.0, 0.0),
        (0.0, 0.0, 1.0, 0.0),
        (0.0, 0.0, 0.0, 1.0),
    )


def validate_matrix4(value: Any) -> Matrix4:
    # This runs over a million times in one portfolio: the pose search composes
    # matrices from builders that already emit canonical Matrix4 tuples, and
    # revalidating them rebuilds every row. Recognise an already-canonical value
    # and hand it straight back; anything else takes the full path below.
    if type(value) is tuple and len(value) == 4:
        for row in value:
            if type(row) is not tuple or len(row) != 4:
                break
            for item in row:
                if type(item) is not float or not isfinite(item):
                    break
            else:
                continue
            break
        else:
            last = value[3]
            if (
                last[0] == 0.0
                and last[1] == 0.0
                and last[2] == 0.0
                and last[3] == 1.0
            ):
                return value
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError("matrix4 must contain four rows")
    rows: list[tuple[float, float, float, float]] = []
    for row in value:
        if not isinstance(row, (list, tuple)) or len(row) != 4:
            raise ValueError("each matrix4 row must contain four numbers")
        numeric = tuple(float(item) for item in row)
        if not all(isfinite(item) for item in numeric):
            raise ValueError("matrix4 values must be finite")
        rows.append(numeric)  # type: ignore[arg-type]
    expected = (0.0, 0.0, 0.0, 1.0)
    if any(abs(rows[3][index] - expected[index]) > 1e-9 for index in range(4)):
        raise ValueError("matrix4 must be affine with last row [0, 0, 0, 1]")
    return tuple(rows)


def _multiply(left: Matrix4, right: Matrix4) -> Matrix4:
    # Unrolled indexing only: the nested generator form issued tens of millions
    # of frames per portfolio. `sum()` itself must stay, because CPython 3.12+
    # sums floats with Neumaier compensation - replacing it with plain left-to-
    # right addition shifts the last digit and moves every program hash.
    r0, r1, r2, r3 = right
    r00, r01, r02, r03 = r0
    r10, r11, r12, r13 = r1
    r20, r21, r22, r23 = r2
    r30, r31, r32, r33 = r3
    out = []
    for a, b, c, d in left:
        out.append((
            sum((a * r00, b * r10, c * r20, d * r30)),
            sum((a * r01, b * r11, c * r21, d * r31)),
            sum((a * r02, b * r12, c * r22, d * r32)),
            sum((a * r03, b * r13, c * r23, d * r33)),
        ))
    return tuple(out)


def compose_matrix4(*matrices: Sequence[Sequence[float]]) -> Matrix4:
    result = identity_matrix4()
    for raw in matrices:
        result = _multiply(validate_matrix4(raw), result)
    return result


def inverse_matrix4(matrix: Sequence[Sequence[float]]) -> Matrix4:
    """Return the inverse of a general affine matrix.

    The affine last row is validated up front.  The inverse is formed from
    the upper-left 3x3 linear block and translated by ``-A^-1 t``.
    """

    value = validate_matrix4(matrix)
    a, b, c = value[0][:3]
    d, e, f = value[1][:3]
    g, h, i = value[2][:3]
    determinant = (
        a * (e * i - f * h)
        - b * (d * i - f * g)
        + c * (d * h - e * g)
    )
    determinant_scale = (
        max(abs(a), abs(b), abs(c))
        * max(abs(d), abs(e), abs(f))
        * max(abs(g), abs(h), abs(i))
    )
    if abs(determinant) <= 1e-12 * determinant_scale:
        raise ValueError("matrix4 is singular and cannot be inverted")
    inverse_determinant = 1.0 / determinant
    linear_inverse = (
        (
            (e * i - f * h) * inverse_determinant,
            (c * h - b * i) * inverse_determinant,
            (b * f - c * e) * inverse_determinant,
        ),
        (
            (f * g - d * i) * inverse_determinant,
            (a * i - c * g) * inverse_determinant,
            (c * d - a * f) * inverse_determinant,
        ),
        (
            (d * h - e * g) * inverse_determinant,
            (b * g - a * h) * inverse_determinant,
            (a * e - b * d) * inverse_determinant,
        ),
    )
    translation = (value[0][3], value[1][3], value[2][3])
    inverse_translation = tuple(
        -sum(linear_inverse[row][column] * translation[column] for column in range(3))
        for row in range(3)
    )
    return validate_matrix4((
        (*linear_inverse[0], inverse_translation[0]),
        (*linear_inverse[1], inverse_translation[1]),
        (*linear_inverse[2], inverse_translation[2]),
        (0.0, 0.0, 0.0, 1.0),
    ))


def translation_matrix4(vector: Sequence[float]) -> Matrix4:
    x, y, z = _vector3(vector, "translation vector")
    return (
        (1.0, 0.0, 0.0, x),
        (0.0, 1.0, 0.0, y),
        (0.0, 0.0, 1.0, z),
        (0.0, 0.0, 0.0, 1.0),
    )


def scale_matrix4(vector: Sequence[float]) -> Matrix4:
    x, y, z = _vector3(vector, "scale vector")
    if min(abs(x), abs(y), abs(z)) <= 1e-9:
        raise ValueError("scale components must be non-zero")
    return (
        (x, 0.0, 0.0, 0.0),
        (0.0, y, 0.0, 0.0),
        (0.0, 0.0, z, 0.0),
        (0.0, 0.0, 0.0, 1.0),
    )


def rotation_matrix4(angles_degrees: Sequence[float]) -> Matrix4:
    x, y, z = (radians(value) for value in _vector3(angles_degrees, "rotation angles"))
    rx = (
        (1.0, 0.0, 0.0, 0.0),
        (0.0, cos(x), -sin(x), 0.0),
        (0.0, sin(x), cos(x), 0.0),
        (0.0, 0.0, 0.0, 1.0),
    )
    ry = (
        (cos(y), 0.0, sin(y), 0.0),
        (0.0, 1.0, 0.0, 0.0),
        (-sin(y), 0.0, cos(y), 0.0),
        (0.0, 0.0, 0.0, 1.0),
    )
    rz = (
        (cos(z), -sin(z), 0.0, 0.0),
        (sin(z), cos(z), 0.0, 0.0),
        (0.0, 0.0, 1.0, 0.0),
        (0.0, 0.0, 0.0, 1.0),
    )
    return _multiply(rz, _multiply(ry, rx))


def shear_matrix4(axis: str, direction: str, amount: float) -> Matrix4:
    indices = {"x": 0, "y": 1, "z": 2}
    row, column = indices.get(axis.lower()), indices.get(direction.lower())
    if row is None or column is None or row == column:
        raise ValueError("shear axis and direction must be different x/y/z axes")
    rows = [list(row_value) for row_value in identity_matrix4()]
    rows[row][column] = float(amount)
    return validate_matrix4(rows)


def mirror_matrix4(normal: Sequence[float]) -> Matrix4:
    x, y, z = _vector3(normal, "mirror normal")
    length = sqrt(x * x + y * y + z * z)
    if length <= 1e-12:
        raise ValueError("mirror normal must be non-zero")
    n = (x / length, y / length, z / length)
    rows = [list(row) for row in identity_matrix4()]
    for row in range(3):
        for column in range(3):
            rows[row][column] = (1.0 if row == column else 0.0) - 2.0 * n[row] * n[column]
    return validate_matrix4(rows)


def matrix4_for_transform(operator: str, parameters: dict[str, Any]) -> Matrix4:
    operator = str(operator).lower()
    if operator == "matrix4":
        return validate_matrix4(parameters.get("matrix4"))
    if operator == "translate":
        return translation_matrix4(parameters.get("vector", (
            parameters.get("x", 0.0), parameters.get("y", 0.0), parameters.get("z", 0.0),
        )))
    if operator == "scale":
        raw = parameters.get("vector", parameters.get("scale", (1.0, 1.0, 1.0)))
        raw = (float(raw),) * 3 if isinstance(raw, (int, float)) else raw
        local = scale_matrix4(raw)
    elif operator == "rotate":
        angles = parameters.get("angles")
        if angles is None:
            axis = str(parameters.get("axis") or "z").lower()
            value = float(parameters.get("angle_degrees", parameters.get("angle", 0.0)))
            angles = (
                value if axis == "x" else 0.0,
                value if axis == "y" else 0.0,
                value if axis == "z" else 0.0,
            )
        local = rotation_matrix4(angles)
    elif operator == "mirror":
        local = mirror_matrix4(parameters.get("normal", (1.0, 0.0, 0.0)))
    elif operator == "shear":
        local = shear_matrix4(
            str(parameters.get("axis") or "x"),
            str(parameters.get("direction") or "z"),
            float(parameters.get("amount", 0.0)),
        )
    else:
        raise ValueError(f"unsupported affine transform: {operator}")

    pivot = parameters.get("pivot", (0.0, 0.0, 0.0))
    if isinstance(pivot, str):
        raise ValueError("symbolic pivot must be resolved before matrix evaluation")
    pivot3 = _vector3(pivot, "pivot")
    if pivot3 == (0.0, 0.0, 0.0):
        return local
    return compose_matrix4(
        translation_matrix4(tuple(-item for item in pivot3)),
        local,
        translation_matrix4(pivot3),
    )


def transform_point3(matrix: Sequence[Sequence[float]], point: Sequence[float]) -> tuple[float, float, float]:
    matrix4 = validate_matrix4(matrix)
    x, y, z = _vector3(point, "point")
    vector = (x, y, z, 1.0)
    result = tuple(sum(matrix4[row][column] * vector[column] for column in range(4)) for row in range(4))
    if abs(result[3] - 1.0) > 1e-9:
        raise ValueError("affine point produced an invalid homogeneous coordinate")
    return tuple(round(result[index], 12) for index in range(3))  # type: ignore[return-value]


def kernel_matrix3x4(matrix: Sequence[Sequence[float]]) -> list[list[float]]:
    return [list(row) for row in validate_matrix4(matrix)[:3]]


def matrix4_to_lists(matrix: Sequence[Sequence[float]]) -> list[list[float]]:
    return [list(row) for row in validate_matrix4(matrix)]


def _vector3(value: Iterable[float], label: str) -> tuple[float, float, float]:
    try:
        items = tuple(float(item) for item in value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must contain three numbers") from exc
    if len(items) != 3 or not all(isfinite(item) for item in items):
        raise ValueError(f"{label} must contain three finite numbers")
    return items  # type: ignore[return-value]


__all__ = [
    "Matrix4", "compose_matrix4", "identity_matrix4", "inverse_matrix4",
    "kernel_matrix3x4",
    "matrix4_for_transform", "matrix4_to_lists", "mirror_matrix4",
    "rotation_matrix4", "scale_matrix4", "shear_matrix4",
    "transform_point3", "translation_matrix4", "validate_matrix4",
]
