"""Prepared rig conversion, matching upstream RGB MoCap Live Link reference.

Original conversion functions: RGB MoCap contributors, MIT.
"""
import re
import numpy as np
from .bone_stream import Y_TO_Z
from .pear_vmc import DISPLAY, NAMES, BODY

SOURCE_TO_UE = np.array(((0., 0., -1.), (1., 0., 0.), (0., 1., 0.)))
YAW = np.array(((0., 1., 0.), (-1., 0., 0.), (0., 0., 1.)))
BLENDER_TO_UE = YAW @ SOURCE_TO_UE @ Y_TO_Z.T


def local_transforms(world, parents):
    """Blender Z-up world matrices -> parent-local Unreal cm / xyzw, without SciPy."""
    world = np.asarray(world, dtype=np.float64)
    count = len(parents)
    if world.shape != (count, 3, 4) or not np.isfinite(world).all():
        raise ValueError('Invalid streaming bone matrices.')
    rotation = BLENDER_TO_UE @ world[:, :, :3] @ SOURCE_TO_UE.T
    position = (BLENDER_TO_UE @ world[:, :, 3, None])[..., 0] * 100.
    if (not np.allclose(rotation.transpose(0, 2, 1) @ rotation, np.eye(3), atol=.003)
            or np.any(np.linalg.det(rotation) <= 0)):
        raise ValueError('Live Link requires rigid bone transforms.')
    local_r, local_p = rotation.copy(), position.copy()
    for i, parent in enumerate(parents):
        if parent >= 0:
            local_r[i] = rotation[parent].T @ rotation[i]
            local_p[i] = rotation[parent].T @ (position[i] - position[parent])
    # Unit quaternion is the largest-eigenvalue vector of this symmetric matrix.
    r = local_r
    k = np.empty((count, 4, 4))
    k[:, 0, 0] = r[:, 0, 0] - r[:, 1, 1] - r[:, 2, 2]
    k[:, 1, 1] = r[:, 1, 1] - r[:, 0, 0] - r[:, 2, 2]
    k[:, 2, 2] = r[:, 2, 2] - r[:, 0, 0] - r[:, 1, 1]
    k[:, 3, 3] = np.trace(r, axis1=1, axis2=2)
    for a, b, value in ((0, 1, r[:, 0, 1]+r[:, 1, 0]),
                        (0, 2, r[:, 0, 2]+r[:, 2, 0]),
                        (1, 2, r[:, 1, 2]+r[:, 2, 1]),
                        (0, 3, r[:, 2, 1]-r[:, 1, 2]),
                        (1, 3, r[:, 0, 2]-r[:, 2, 0]),
                        (2, 3, r[:, 1, 0]-r[:, 0, 1])):
        k[:, a, b] = k[:, b, a] = value
    quat = np.linalg.eigh(k)[1][:, :, -1]
    quat *= np.where(quat[:, 3:] < 0, -1., 1.)
    return np.concatenate((local_p, quat), axis=1).tolist()


def rig_schema(rig):
    bones = rig.bones
    if not 0 < len(bones) <= 256:
        raise ValueError('Live Link supports 1–256 bones per person.')
    names = [b[0] for b in bones]
    parents = [int(b[1]) for b in bones]
    if (len({n.casefold() for n in names}) != len(names) or any(not n or len(n.encode('utf-16-le')) > 240 for n in names)
            or parents[0] != -1 or any(not 0 <= p < i for i, p in enumerate(parents[1:], 1))):
        raise ValueError('Invalid streaming bone hierarchy.')
    lengths = np.asarray([b[3] for b in bones], dtype=float) * 100.
    if not np.isfinite(lengths).all() or np.any(lengths <= 0):
        raise ValueError('Invalid streaming bone lengths.')
    rest = np.asarray([b[2] for b in bones]).reshape(-1, 3, 4)
    return dict(rig=rig.key, names=names, parents=parents, rest=local_transforms(rest, parents),
                lengths=lengths.tolist())


def subject_name(actor, name):
    """Readable identity, stable across seeks/reconnects with the same person name."""
    if len(actor) != 64 or any(c not in '0123456789abcdef' for c in actor):
        raise ValueError('Invalid streaming person ID.')
    label = re.sub(r'[\W_]+', '_', str(name), flags=re.UNICODE).strip('_')[:24] or 'Person'
    return f'RGBMoCap_{label}_{actor[:8]}'


