import importlib
import inspect
import warnings
from typing import Any, Callable, Dict, Tuple, Union

from torch import _C
from torch.onnx import _constants, errors

__all__ = [
    "get_op_supported_version",
    "get_ops_in_version",
    "get_registered_op",
    "is_registered_op",
    "is_registered_version",
    "register_op",
    "register_ops_helper",
    "register_ops_in_version",
    "register_version",
    "unregister_op",
]

_SymbolicFunction = Callable[..., Union[_C.Value, Tuple[_C.Value]]]

"""
The symbolic registry "_registry" is a dictionary that maps operators
(for a specific domain and opset version) to their symbolic functions.
An operator is defined by its domain, opset version, and opname.
The keys are tuples (domain, version), (where domain is a string, and version is an int),
and the operator's name (string).
The map's entries are as follows : _registry[(domain, version)][op_name] = op_symbolic
"""
_registry: Dict[
    Tuple[str, int],
    Dict[str, _SymbolicFunction],
] = {}

_symbolic_versions: Dict[Union[int, str], Any] = {}


def _import_symbolic_opsets():
    for opset_version in range(
        _constants.ONNX_MIN_OPSET, _constants.ONNX_MAX_OPSET + 1
    ):
        module = importlib.import_module(f"torch.onnx.symbolic_opset{opset_version}")
        global _symbolic_versions
        _symbolic_versions[opset_version] = module


def register_version(domain: str, version: int):
    if not is_registered_version(domain, version):
        global _registry
        _registry[(domain, version)] = {}
    register_ops_in_version(domain, version)


def register_ops_helper(domain: str, version: int, iter_version: int):
    for domain, op_name, op_func in get_ops_in_version(iter_version):
        if not is_registered_op(op_name, domain, version):
            register_op(op_name, op_func, domain, version)


def register_ops_in_version(domain: str, version: int):
    """Iterates through the symbolic functions of the specified opset version, and the
    previous opset versions for operators supported in previous versions.

    Opset 9 is the base version. It is selected as the base version because
        1. It is the first opset version supported by PyTorch export.
        2. opset 9 is more robust than previous opset versions. Opset versions like 7/8 have limitations
            that certain basic operators cannot be expressed in ONNX. Instead of basing on these limitations,
            we chose to handle them as special cases separately.

    Backward support for opset versions beyond opset 7 is not in our roadmap.

    For opset versions other than 9, by default they will inherit the symbolic functions defined in
    symbolic_opset9.py.

    To extend support for updated operators in different opset versions on top of opset 9,
    simply add the updated symbolic functions in the respective symbolic_opset{version}.py file.
    Checkout topk in symbolic_opset10.py, and upsample_nearest2d in symbolic_opset8.py for example.
    """
    iter_version = version
    while iter_version != 9:
        register_ops_helper(domain, version, iter_version)
        if iter_version > 9:
            iter_version = iter_version - 1
        else:
            iter_version = iter_version + 1

    register_ops_helper(domain, version, 9)


def get_ops_in_version(version: int):
    if not _symbolic_versions:
        _import_symbolic_opsets()
    members = inspect.getmembers(_symbolic_versions[version])
    domain_opname_ops = []
    for obj in members:
        if isinstance(obj[1], type) and hasattr(obj[1], "domain"):
            ops = inspect.getmembers(obj[1], predicate=inspect.isfunction)
            for op in ops:
                domain_opname_ops.append((obj[1].domain, op[0], op[1]))  # type: ignore[attr-defined]

        elif inspect.isfunction(obj[1]):
            if obj[0] == "_len":
                obj = ("len", obj[1])
            if obj[0] == "_list":
                obj = ("list", obj[1])
            if obj[0] == "_any":
                obj = ("any", obj[1])
            if obj[0] == "_all":
                obj = ("all", obj[1])
            domain_opname_ops.append(("", obj[0], obj[1]))
    return domain_opname_ops


def is_registered_version(domain: str, version: int):
    global _registry
    return (domain, version) in _registry


def register_op(opname, op, domain, version):
    if domain is None or version is None:
        warnings.warn(
            "ONNX export failed. The ONNX domain and/or version to register are None."
        )
    global _registry
    if not is_registered_version(domain, version):
        _registry[(domain, version)] = {}
    _registry[(domain, version)][opname] = op


def is_registered_op(opname: str, domain: str, version: int):
    if domain is None or version is None:
        warnings.warn("ONNX export failed. The ONNX domain and/or version are None.")
    global _registry
    return (domain, version) in _registry and opname in _registry[(domain, version)]


def unregister_op(opname: str, domain: str, version: int):
    global _registry
    if is_registered_op(opname, domain, version):
        del _registry[(domain, version)][opname]
        if not _registry[(domain, version)]:
            del _registry[(domain, version)]
    else:
        warnings.warn("The opname " + opname + " is not registered.")


def get_op_supported_version(opname: str, domain: str, version: int):
    iter_version = version
    while iter_version <= _constants.ONNX_MAX_OPSET:
        ops = [(op[0], op[1]) for op in get_ops_in_version(iter_version)]
        if (domain, opname) in ops:
            return iter_version
        iter_version += 1
    return None


def get_registered_op(opname: str, domain: str, version: int) -> _SymbolicFunction:
    if domain is None or version is None:
        warnings.warn("ONNX export failed. The ONNX domain and/or version are None.")
    global _registry
    if not is_registered_op(opname, domain, version):
        raise errors.UnsupportedOperatorError(
            domain, opname, version, get_op_supported_version(opname, domain, version)
        )
    return _registry[(domain, version)][opname]
