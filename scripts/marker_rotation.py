"""Preserve a marker's full rigid rotation during grasp, including axial twist."""
import numpy as np
from scipy.spatial.transform import Rotation, Slerp


def enforce_rigid_marker_rotation(frames, attach=235, release=457, settled=474):
    """Change only marker_quaternion (wxyz), preserving all other frame fields.

    During attachment, Q_marker = Q_root * (Q_root_attach^-1 * Q_marker_attach).
    The release interpolates the complete quaternion to the existing settled
    orientation. Smoothstep timing matches the existing positional drop timing.
    This is idempotent and does not require rerunning any pose optimization.
    """
    def read(value):
        return Rotation.from_quat(np.asarray(value, dtype=float)[[1, 2, 3, 0]])

    def write(rotation, reference=None):
        xyzw = rotation.as_quat()
        value = xyzw[[3, 0, 1, 2]]
        if reference is not None and np.dot(value, reference) < 0:
            value = -value
        return value.tolist()

    attached_marker = read(frames[attach]['marker_quaternion'])
    relative_marker = read(frames[attach]['right_root_quaternion']).inv() * attached_marker
    final_value = frames[settled]['marker_quaternion'][:]
    final_rotation = read(final_value)
    previous = frames[attach]['marker_quaternion'][:]
    for index in range(attach + 1, release + 1):
        root = read(frames[index]['right_root_quaternion'])
        value = write(root * relative_marker, previous)
        frames[index]['marker_quaternion'] = value
        previous = value

    release_rotation = read(frames[release]['marker_quaternion'])
    path = Slerp([0., 1.], Rotation.from_quat(
        np.stack([release_rotation.as_quat(), final_rotation.as_quat()])))
    for index in range(release + 1, settled):
        fraction = (index - release) / float(settled - release)
        fraction = fraction * fraction * (3. - 2. * fraction)
        value = write(path(fraction), previous)
        frames[index]['marker_quaternion'] = value
        previous = value
    # Retain the original endpoint values and every later frame exactly.
    frames[settled]['marker_quaternion'] = final_value
    return frames
