from __future__ import annotations

import ast
import math
import operator

from tools.base import ToolDef

ALLOWED_OPS: dict = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.USub: operator.neg,
}

ALLOWED_CONSTANTS: dict = {
    "pi": math.pi,
    "e": math.e,
    "tau": math.tau,
}

ALLOWED_FUNCTIONS: dict = {
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
        op = ALLOWED_OPS.get(type(node.op))
        if op is None:
            raise ValueError(f"Operator not allowed: {type(node.op).__name__}")
        left = self.visit(node.left)
        right = self.visit(node.right)
        return op(left, right)

    def visit_UnaryOp(self, node: ast.UnaryOp) -> int | float:
        op = ALLOWED_OPS.get(type(node.op))
        if op is None:
            raise ValueError(f"Unary operator not allowed: {type(node.op).__name__}")
        return op(self.visit(node.operand))

    def visit_Call(self, node: ast.Call) -> int | float:
        if not isinstance(node.func, ast.Name):
            raise ValueError("Only simple function calls are allowed")
        name = node.func.id
        if name not in ALLOWED_FUNCTIONS:
            raise ValueError(f"Function '{name}' is not allowed")
        args = [self.visit(a) for a in node.args]
        return ALLOWED_FUNCTIONS[name](*args)

    def visit_Name(self, node: ast.Name) -> int | float:
        if node.id in ALLOWED_CONSTANTS:
            return ALLOWED_CONSTANTS[node.id]
        raise ValueError(f"Name '{node.id}' is not allowed")

    def visit_Expr(self, node: ast.Expr):
        return self.visit(node.value)

    def generic_visit(self, node: ast.AST):
        raise ValueError(f"Node type not allowed: {type(node).__name__}")


def _safe_eval(expression: str) -> int | float:
    expr = expression.strip()
    # Replace ^ with ** (Grok uses ^ for power, Python uses **)
    expr = expr.replace("^", "**")
    tree = ast.parse(expr, mode="eval")
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
            result = _safe_eval(expression)
            if isinstance(result, float) and result == int(result) and abs(result) < 1e15:
                result = int(result)
            return str(result)
        except Exception as exc:
            return f"Error: {exc}"
