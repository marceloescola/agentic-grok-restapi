from __future__ import annotations

import ast
import math
import operator
from typing import Callable, Dict

from numba import njit, float64, int32

from tools.base import ToolDef

# ---------------------------------------------------------------------------
# Numba fast-path for pure arithmetic expressions
# ---------------------------------------------------------------------------

@njit(cache=True)
def _skip_ws(s: bytes, i: int32) -> int32:
    while i < len(s) and s[i] == 32:  # ord(' ')
        i += 1
    return i


@njit(cache=True)
def _parse_float_numba(s: bytes, i: int32) -> tuple[float64, int32]:
    """Parse a float from bytes. Supports optional leading +/-."""
    i = _skip_ws(s, i)
    sign: float64 = 1.0
    if i < len(s) and s[i] == 45:  # ord('-')
        sign = -1.0
        i += 1
    elif i < len(s) and s[i] == 43:  # ord('+')
        i += 1

    val: float64 = 0.0
    has_digits: bool = False
    while i < len(s) and 48 <= s[i] <= 57:  # 0-9
        val = val * 10.0 + float64(s[i] - 48)
        i += 1
        has_digits = True

    if i < len(s) and s[i] == 46:  # ord('.')
        i += 1
        frac: float64 = 0.1
        while i < len(s) and 48 <= s[i] <= 57:
            val += float64(s[i] - 48) * frac
            frac *= 0.1
            i += 1
            has_digits = True

    if not has_digits:
        return 0.0, i
    return sign * val, i


@njit(cache=True)
def _parse_primary_numba(s: bytes, i: int32) -> tuple[float64, int32]:
    i = _skip_ws(s, i)
    if i < len(s) and s[i] == 40:  # ord('(')
        val, i = _parse_expr_numba(s, i + 1)
        i = _skip_ws(s, i)
        if i < len(s) and s[i] == 41:  # ord(')')
            i += 1
        return val, i
    return _parse_float_numba(s, i)


@njit(cache=True)
def _parse_unary_numba(s: bytes, i: int32) -> tuple[float64, int32]:
    i = _skip_ws(s, i)
    sign: float64 = 1.0
    while i < len(s) and (s[i] == 45 or s[i] == 43):  # ord('-') or ord('+')
        if s[i] == 45:
            sign = -sign
        i += 1
    val, i = _parse_primary_numba(s, i)
    return sign * val, i


@njit(cache=True)
def _parse_power_numba(s: bytes, i: int32) -> tuple[float64, int32]:
    left, i = _parse_unary_numba(s, i)
    i = _skip_ws(s, i)
    while i < len(s) and s[i] == 94:  # ord('^')
        right, i = _parse_unary_numba(s, i + 1)
        left = left ** right
        i = _skip_ws(s, i)
    return left, i


@njit(cache=True)
def _parse_term_numba(s: bytes, i: int32) -> tuple[float64, int32]:
    left, i = _parse_power_numba(s, i)
    i = _skip_ws(s, i)
    while i < len(s):
        if s[i] == 42:  # ord('*')
            right, i = _parse_power_numba(s, i + 1)
            left *= right
            i = _skip_ws(s, i)
        elif s[i] == 47:  # ord('/')
            right, i = _parse_power_numba(s, i + 1)
            left /= right
            i = _skip_ws(s, i)
        else:
            break
    return left, i


@njit(cache=True)
def _parse_expr_numba(s: bytes, i: int32) -> tuple[float64, int32]:
    left, i = _parse_term_numba(s, i)
    i = _skip_ws(s, i)
    while i < len(s):
        if s[i] == 43:  # ord('+')
            right, i = _parse_term_numba(s, i + 1)
            left += right
            i = _skip_ws(s, i)
        elif s[i] == 45:  # ord('-')
            right, i = _parse_term_numba(s, i + 1)
            left -= right
            i = _skip_ws(s, i)
        else:
            break
    return left, i


@njit(cache=True)
def _fast_eval_bytes(s: bytes) -> float64:
    val, i = _parse_expr_numba(s, 0)
    return val


_ALLOWED_SIMPLE_CHARS: set[int] = set(map(ord, "0123456789.+-*/^() "))


def _is_simple_arithmetic(expr: str) -> bool:
    return all(ord(ch) in _ALLOWED_SIMPLE_CHARS for ch in expr)


# ---------------------------------------------------------------------------
# AST-based safe evaluator (fallback for functions/constants)
# ---------------------------------------------------------------------------

_ALLOWED_OPS: Dict[type[ast.operator], Callable[[float, float], float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.USub: operator.neg,
}

_ALLOWED_CONSTANTS: Dict[str, float] = {
    "pi": math.pi,
    "e": math.e,
    "tau": math.tau,
}

_ALLOWED_FUNCTIONS: Dict[str, Callable[..., float]] = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sqrt": math.sqrt,
    "pow": pow,
    "log": math.log,
    "log10": math.log10,
    "log2": math.log2,
    "exp": math.exp,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "asin": math.asin,
    "acos": math.acos,
    "atan": math.atan,
    "degrees": math.degrees,
    "radians": math.radians,
    "ceil": math.ceil,
    "floor": math.floor,
    "factorial": math.factorial,
    "gcd": math.gcd,
}


class _SafeVisitor(ast.NodeVisitor):
    def visit_Constant(self, node: ast.Constant) -> int | float:
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError(f"Unsupported constant type: {type(node.value).__name__}")

    def visit_BinOp(self, node: ast.BinOp) -> int | float:
        op: Callable[[float, float], float] | None = _ALLOWED_OPS.get(type(node.op))
        if op is None:
            raise ValueError(f"Operator not allowed: {type(node.op).__name__}")
        left: int | float = self.visit(node.left)
        right: int | float = self.visit(node.right)
        return op(left, right)

    def visit_UnaryOp(self, node: ast.UnaryOp) -> int | float:
        op: Callable[[float], float] | None = _ALLOWED_OPS.get(type(node.op))
        if op is None:
            raise ValueError(f"Unary operator not allowed: {type(node.op).__name__}")
        return op(self.visit(node.operand))

    def visit_Call(self, node: ast.Call) -> int | float:
        if not isinstance(node.func, ast.Name):
            raise ValueError("Only simple function calls are allowed")
        name: str = node.func.id
        if name not in _ALLOWED_FUNCTIONS:
            raise ValueError(f"Function '{name}' is not allowed")
        args: list[int | float] = [self.visit(a) for a in node.args]
        return _ALLOWED_FUNCTIONS[name](*args)

    def visit_Name(self, node: ast.Name) -> int | float:
        if node.id in _ALLOWED_CONSTANTS:
            return _ALLOWED_CONSTANTS[node.id]
        raise ValueError(f"Name '{node.id}' is not allowed")

    def visit_Expr(self, node: ast.Expr) -> int | float:
        return self.visit(node.value)

    def generic_visit(self, node: ast.AST) -> None:
        raise ValueError(f"Node type not allowed: {type(node).__name__}")


def _safe_eval(expression: str) -> int | float:
    expr: str = expression.strip()

    # Numba fast path: pure arithmetic (numbers, +, -, *, /, ^, parentheses)
    if _is_simple_arithmetic(expr):
        try:
            return _fast_eval_bytes(expr.encode("ascii"))
        except Exception:
            pass  # Fall back to AST evaluator

    # Fallback: full AST with functions and constants
    expr = expr.replace("^", "**")
    tree: ast.Expression = ast.parse(expr, mode="eval")
    visitor = _SafeVisitor()
    return visitor.visit(tree.body)


class CalculatorTool:
    @property
    def definition(self) -> ToolDef:
        return ToolDef(
            name="calculator",
            description="Safely evaluate a mathematical expression. Supports: +, -, *, /, **, ^, %, sqrt, sin, cos, tan, log, exp, pi, e, and more.",
            parameters={"expression": "the mathematical expression to evaluate"},
        )

    async def run(self, expression: str = "") -> str:
        if not expression.strip():
            return "Error: empty expression"
        try:
            result: int | float = _safe_eval(expression)
            if isinstance(result, float) and result == int(result) and abs(result) < 1e15:
                result = int(result)
            return str(result)
        except Exception as exc:
            return f"Error: {exc}"
