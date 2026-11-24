"""Restricciones entre variables, escritas como una fórmula simple.

Ejemplos:   vol_naoh + vol_hcl <= 40        velocidad >= 2 * vol_naoh

Solo se permiten números, nombres de variables, + - * / **, comparaciones,
'and'/'or' y las funciones abs, min y max. Cualquier otra cosa se rechaza
(la fórmula nunca se ejecuta como código libre).
"""
from __future__ import annotations

import ast
import operator
import re

_BINARIOS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
             ast.Div: operator.truediv, ast.Pow: operator.pow}
_COMPARACIONES = {ast.Lt: operator.lt, ast.LtE: operator.le, ast.Gt: operator.gt,
                  ast.GtE: operator.ge, ast.Eq: operator.eq, ast.NotEq: operator.ne}
_FUNCIONES = {"abs": abs, "min": min, "max": max}


class ErrorRestriccion(ValueError):
    pass


def compilar(formula: str, nombres: list[str]):
    """Devuelve una función(valores: dict) -> bool. Lanza ErrorRestriccion si la fórmula no vale."""
    texto = formula.replace("≤", "<=").replace("≥", ">=")
    texto = re.sub(r"(?<=\d),(?=\d)", ".", texto)          # acepta coma decimal: 2,5 -> 2.5
    try:
        arbol = ast.parse(texto, mode="eval")
    except SyntaxError:
        raise ErrorRestriccion(f"No se entiende la restricción «{formula}».")
    tiene_comparacion = any(isinstance(n, ast.Compare) for n in ast.walk(arbol))
    if not tiene_comparacion:
        raise ErrorRestriccion(f"La restricción «{formula}» necesita una comparación (<=, >=, <, >).")

    def revisar(nodo):
        if isinstance(nodo, ast.Expression):
            return revisar(nodo.body)
        if isinstance(nodo, ast.Constant) and isinstance(nodo.value, (int, float)):
            return
        if isinstance(nodo, ast.Name):
            if nodo.id not in nombres:
                raise ErrorRestriccion(f"«{nodo.id}» no es una variable del experimento "
                                       f"(disponibles: {', '.join(nombres)}).")
            return
        if isinstance(nodo, ast.BinOp) and type(nodo.op) in _BINARIOS:
            return [revisar(nodo.left), revisar(nodo.right)]
        if isinstance(nodo, ast.UnaryOp) and isinstance(nodo.op, (ast.USub, ast.UAdd)):
            return revisar(nodo.operand)
        if isinstance(nodo, ast.Compare) and all(type(o) in _COMPARACIONES for o in nodo.ops):
            return [revisar(n) for n in [nodo.left, *nodo.comparators]]
        if isinstance(nodo, ast.BoolOp):
            return [revisar(n) for n in nodo.values]
        if isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name) \
                and nodo.func.id in _FUNCIONES and not nodo.keywords:
            return [revisar(n) for n in nodo.args]
        raise ErrorRestriccion(f"La restricción «{formula}» usa algo que no está permitido.")

    revisar(arbol)

    def evaluar(nodo, v):
        if isinstance(nodo, ast.Expression):
            return evaluar(nodo.body, v)
        if isinstance(nodo, ast.Constant):
            return nodo.value
        if isinstance(nodo, ast.Name):
            return v[nodo.id]
        if isinstance(nodo, ast.BinOp):
            return _BINARIOS[type(nodo.op)](evaluar(nodo.left, v), evaluar(nodo.right, v))
        if isinstance(nodo, ast.UnaryOp):
            valor = evaluar(nodo.operand, v)
            return -valor if isinstance(nodo.op, ast.USub) else valor
        if isinstance(nodo, ast.Compare):
            izquierda = evaluar(nodo.left, v)
            for op, derecho in zip(nodo.ops, nodo.comparators):
                derecha = evaluar(derecho, v)
                if not _COMPARACIONES[type(op)](izquierda, derecha):
                    return False
                izquierda = derecha
            return True
        if isinstance(nodo, ast.BoolOp):
            valores = [evaluar(n, v) for n in nodo.values]
            return all(valores) if isinstance(nodo.op, ast.And) else any(valores)
        if isinstance(nodo, ast.Call):
            return _FUNCIONES[nodo.func.id](*[evaluar(n, v) for n in nodo.args])
        raise ErrorRestriccion("Restricción no válida.")

    def funcion(valores: dict) -> bool:
        try:
            return bool(evaluar(arbol, valores))
        except ZeroDivisionError:
            return False

    return funcion
