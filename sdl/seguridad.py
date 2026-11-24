"""Protocolo de seguridad y verificación previa.

Capas (de la más cercana al hardware a la más lejana):

  0. Corte físico: botón de parada de emergencia que corta la potencia de los
     actuadores (cableado, no depende de ningún programa).
  1. Firmware del ESP32: límites duros (tiempo máximo de válvula abierta, recorrido
     del brazo), vigilancia del latido de la PC y estado seguro al arrancar.
  2. Módulos (PC): cada orden se compara con los límites absolutos del equipo.
  3. Experimento: límites elegidos por el químico, restricciones entre variables y
     volumen máximo del vaso. Toda propuesta del optimizador pasa por acá ANTES de
     ejecutarse.
  4. Personas: lista previa obligatoria, confirmación de reactivos, aprobación de cada
     propuesta (modo supervisado), tiempos de espera que dejan todo seguro si nadie
     responde, y parada de emergencia siempre visible en la pantalla.

Este archivo implementa las capas 3 y 4 y la verificación previa a una campaña.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path

from .modelos import ALCANZAR, Experimento, es_referencia, escribir_yaml, leer_yaml
from .restricciones import ErrorRestriccion, compilar

OK, AVISO, ERROR = "ok", "aviso", "error"

CONFIG_INICIAL = {
    "tiempo_espera_usuario_s": 900,     # sin respuesta en este tiempo -> todo a estado seguro
    "llenado_maximo": 0.8,              # fracción máxima de la capacidad del vaso
    "lista_previa": [
        "Tengo puestos antiparras, guantes y guardapolvo.",
        "Los reactivos cargados son los indicados y están rotulados.",
        "El vaso de reacción está limpio, vacío y en su lugar.",
        "La zona de movimiento del brazo está despejada.",
        "Tengo al alcance el botón de parada de emergencia.",
        "La ventilación es la adecuada para esta reacción.",
    ],
    # Pares de reactivos que no deben mezclarse. Cada lado es una lista de palabras clave
    # separadas por "|". La lista es orientativa y NO reemplaza el criterio del químico.
    "incompatibilidades": [
        ["hipoclorito|lavandina", "acido|hcl|h2so4|hno3", "libera cloro gaseoso"],
        ["hipoclorito|lavandina", "amoniaco|nh3|amonio", "forma cloraminas tóxicas"],
        ["acido nitrico|hno3", "etanol|metanol|acetona|alcohol|glicerina", "reacción violenta"],
        ["peroxido|h2o2|agua oxigenada", "acetona", "puede formar peróxidos explosivos"],
        ["cianuro|kcn|nacn", "acido|hcl|h2so4|hno3", "libera cianuro de hidrógeno"],
        ["azida|nan3", "acido|hcl|h2so4|hno3", "libera ácido hidrazoico"],
        ["sulfuro|na2s", "acido|hcl|h2so4|hno3", "libera sulfuro de hidrógeno"],
        ["permanganato|kmno4", "glicerina|glicerol|etanol|acido sulfurico", "riesgo de ignición"],
        ["sodio metalico|potasio metalico|hidruro", "agua|acuos", "libera hidrógeno y puede encenderse"],
    ],
}


@dataclass
class Chequeo:
    nivel: str      # "ok" | "aviso" | "error"
    texto: str


def cargar_config(carpeta: Path) -> dict:
    ruta = Path(carpeta) / "seguridad.yaml"
    datos = leer_yaml(ruta)
    if not datos:
        datos = dict(CONFIG_INICIAL)
        escribir_yaml(ruta, datos)
    for clave, valor in CONFIG_INICIAL.items():
        datos.setdefault(clave, valor)
    return datos


def _simple(texto: str) -> str:
    t = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    return t.lower()


def incompatibilidades(reactivos: dict, config: dict) -> list[str]:
    """Pares de reactivos cargados que figuran como incompatibles."""
    avisos = []
    nombres = [(m, r) for m, r in reactivos.items() if str(r).strip()]
    for (_, a), (_, b) in combinations(nombres, 2):
        sa, sb = _simple(a), _simple(b)
        for lado1, lado2, motivo in config.get("incompatibilidades", []):
            c1, c2 = lado1.split("|"), lado2.split("|")
            if (any(c in sa for c in c1) and any(c in sb for c in c2)) or \
               (any(c in sb for c in c1) and any(c in sa for c in c2)):
                avisos.append(f"«{a}» y «{b}»: {motivo}.")
                break
    return avisos


# --- utilidades sobre el protocolo --------------------------------------------
def resolver(valor, valores: dict):
    """Devuelve el número de un parámetro: literal o '$variable'."""
    if es_referencia(valor):
        return valores[valor[1:]]
    return valor


def volumen_total(exp: Experimento, gestor, valores: dict) -> float:
    """Mililitros que el protocolo agrega al vaso con estos valores de variables."""
    total = 0.0
    for paso in exp.protocolo:
        if paso.tipo != "accion" or paso.modulo not in gestor.modulos:
            continue
        definicion = gestor.modulos[paso.modulo].acciones().get(paso.accion) or {}
        parametro = definicion.get("agrega_volumen")
        if parametro and parametro in paso.parametros:
            try:
                total += float(resolver(paso.parametros[parametro], valores))
            except (KeyError, TypeError, ValueError):
                pass
    return total


def comprobar_propuesta(exp: Experimento, gestor, valores: dict, config: dict) -> list[str]:
    """Capa 3: revisa una propuesta concreta antes de ejecutarla. Devuelve los problemas."""
    problemas = []
    for v in exp.variables:
        x = valores.get(v.nombre)
        if x is None or not (v.minimo - 1e-9 <= x <= v.maximo + 1e-9):
            problemas.append(f"{v.etiqueta} = {x} está fuera de los límites del experimento.")
    nombres = [v.nombre for v in exp.variables]
    for formula in exp.restricciones:
        try:
            if formula.strip() and not compilar(formula, nombres)(valores):
                problemas.append(f"No cumple la restricción «{formula}».")
        except (ErrorRestriccion, KeyError):
            problemas.append(f"Restricción no válida: «{formula}».")
    limite = float(config.get("llenado_maximo", 0.8)) * float(exp.capacidad_vaso_ml)
    volumen = volumen_total(exp, gestor, valores)
    if volumen > limite + 1e-9:
        problemas.append(f"El volumen total ({volumen:.1f} mL) supera el máximo del vaso ({limite:.0f} mL).")
    for paso in exp.protocolo:
        if paso.tipo == "accion" and paso.modulo in gestor.modulos:
            try:
                p = {k: resolver(x, valores) for k, x in paso.parametros.items()}
                gestor.modulos[paso.modulo].comprobar(paso.accion, p)
            except Exception as error:
                problemas.append(str(error))
    return problemas


# --- verificación previa --------------------------------------------------------
def verificar(exp: Experimento, gestor, historial, config: dict) -> list[Chequeo]:
    """Revisa TODO antes de empezar. Si hay algún 'error', la campaña no arranca."""
    c: list[Chequeo] = []
    err = lambda t: c.append(Chequeo(ERROR, t))
    avi = lambda t: c.append(Chequeo(AVISO, t))
    bien = lambda t: c.append(Chequeo(OK, t))
    n_inicio = 0

    # 1. Definición del experimento
    if not exp.variables:
        err("El experimento no tiene variables para ajustar.")
    if not exp.objetivos:
        err("El experimento no tiene objetivos para optimizar.")
    if not exp.protocolo:
        err("El protocolo está vacío.")
    if exp.max_experimentos < 1:
        err("El número máximo de experimentos debe ser al menos 1.")
    nombres = [v.nombre for v in exp.variables]
    if len(set(nombres)) != len(nombres):
        err("Hay variables con el mismo nombre.")
    for v in exp.variables:
        if not v.maximo > v.minimo:
            err(f"Variable «{v.etiqueta}»: el máximo debe ser mayor que el mínimo.")
    for o in exp.objetivos:
        if o.direccion == ALCANZAR and (o.valor is None or o.tolerancia is None or o.tolerancia <= 0):
            err(f"Objetivo «{o.etiqueta}»: para alcanzar un valor hacen falta el valor y la tolerancia.")
    if not any(o.tiene_meta() for o in exp.objetivos) and exp.objetivos:
        avi("Ningún objetivo tiene meta: la campaña solo terminará por el máximo de experimentos "
            "o cuando usted la finalice.")
    if not any(x.nivel == ERROR for x in c):
        bien(f"Definición correcta: {len(exp.variables)} variable(s), {len(exp.objetivos)} objetivo(s), "
             f"{len(exp.protocolo)} paso(s).")
    n_inicio = len(c)

    # 2. Variables contra los módulos disponibles
    usadas_en: dict[str, list] = {n: [] for n in nombres}
    for i, paso in enumerate(exp.protocolo, 1):
        if paso.tipo == "accion":
            for parametro, valor in paso.parametros.items():
                if es_referencia(valor):
                    usadas_en.setdefault(valor[1:], []).append((i, paso, parametro))
        elif paso.tipo == "esperar" and es_referencia(paso.segundos):
            usadas_en.setdefault(paso.segundos[1:], []).append((i, paso, "segundos"))
        elif paso.tipo == "ajuste_manual":
            usadas_en.setdefault(paso.variable, []).append((i, paso, ""))
    for nombre in usadas_en:
        if nombre not in nombres:
            err(f"El protocolo usa la variable «{nombre}», que no está definida.")
    for v in exp.variables:
        usos = usadas_en.get(v.nombre, [])
        if not usos:
            err(f"La variable «{v.etiqueta}» no se usa en ningún paso del protocolo.")
            continue
        if v.origen == "modulo":
            modulo = gestor.modulos.get(v.modulo)
            if modulo is None:
                err(f"No se puede ajustar «{v.etiqueta}»: el módulo «{v.modulo}» no está "
                    f"instalado o está desactivado.")
                continue
            d = (modulo.acciones().get(v.accion) or {}).get("parametros", {}).get(v.parametro)
            if d is None or not d.get("optimizable"):
                err(f"No se puede ajustar «{v.etiqueta}»: {modulo.etiqueta} no ofrece ese ajuste.")
                continue
            if "min" in d and v.minimo < d["min"] - 1e-9 or "max" in d and v.maximo > d["max"] + 1e-9:
                err(f"«{v.etiqueta}»: el rango {v.minimo:g}–{v.maximo:g} {v.unidad} excede lo que permite "
                    f"{modulo.etiqueta} ({d.get('min', '-')}–{d.get('max', '-')} {d.get('unidad', '')}).")
            for i, paso, parametro in usos:
                if (paso.tipo, paso.modulo, paso.accion, parametro) != ("accion", v.modulo, v.accion, v.parametro):
                    err(f"Paso {i}: la variable «{v.etiqueta}» pertenece a otro ajuste "
                        f"({modulo.etiqueta}) y no puede usarse ahí.")
        elif v.origen == "tiempo":
            if any(paso.tipo != "esperar" for _, paso, _ in usos):
                err(f"«{v.etiqueta}» es un tiempo de espera y solo puede usarse en pasos de espera.")
            if v.minimo < 0:
                err(f"«{v.etiqueta}»: un tiempo no puede ser negativo.")
        elif v.origen == "manual":
            if any(paso.tipo != "ajuste_manual" for _, paso, _ in usos):
                err(f"«{v.etiqueta}» la ajusta el usuario: debe usarse en un paso de ajuste manual.")

    # 3. Pasos del protocolo
    medidos, usados = set(), set()
    for i, paso in enumerate(exp.protocolo, 1):
        if paso.tipo == "accion":
            modulo = gestor.modulos.get(paso.modulo)
            if modulo is None:
                err(f"Paso {i}: el módulo «{paso.modulo}» no está instalado o está desactivado.")
                continue
            usados.add(paso.modulo)
            definicion = modulo.acciones().get(paso.accion)
            if definicion is None:
                err(f"Paso {i}: {modulo.etiqueta} no tiene la acción «{paso.accion}».")
                continue
            # Se prueba la orden con los valores fijos del paso; donde hay una variable
            # se usa su mínimo (el rango de cada variable ya se revisó arriba).
            prueba = {}
            for parametro, valor in paso.parametros.items():
                if es_referencia(valor):
                    variable = exp.variable(valor[1:])
                    if variable is not None:
                        prueba[parametro] = variable.minimo
                else:
                    prueba[parametro] = valor
            try:
                modulo.comprobar(paso.accion, prueba)
            except Exception as error:
                err(f"Paso {i}: {error}")
        elif paso.tipo == "esperar":
            if not es_referencia(paso.segundos):
                try:
                    if float(paso.segundos) < 0:
                        err(f"Paso {i}: el tiempo de espera no puede ser negativo.")
                except (TypeError, ValueError):
                    err(f"Paso {i}: el tiempo de espera no es un número.")
        elif paso.tipo == "medir":
            o = exp.objetivo(paso.objetivo)
            if o is None:
                err(f"Paso {i}: mide «{paso.objetivo}», que no es un objetivo del experimento.")
                continue
            medidos.add(o.nombre)
        elif paso.tipo in ("confirmar",) and not paso.mensaje.strip():
            err(f"Paso {i}: el pedido de confirmación no tiene texto.")
    for o in exp.objetivos:
        if o.nombre not in medidos:
            err(f"El objetivo «{o.etiqueta}» no se mide en ningún paso del protocolo.")
        if o.medicion == "modulo":
            modulo = gestor.modulos.get(o.modulo)
            if modulo is None:
                err(f"No se puede medir «{o.etiqueta}»: el módulo «{o.modulo}» no está instalado "
                    f"o está desactivado.")
            elif o.magnitud not in modulo.mediciones():
                err(f"No se puede medir «{o.etiqueta}»: {modulo.etiqueta} no mide esa magnitud.")
            else:
                usados.add(o.modulo)
    if len(c) == n_inicio:
        bien("Todas las variables, pasos y mediciones son posibles con los módulos instalados.")
    n_inicio = len(c)

    # 4. Restricciones y volumen
    restricciones = []
    for formula in exp.restricciones:
        if formula.strip():
            try:
                restricciones.append(compilar(formula, nombres))
            except ErrorRestriccion as error:
                err(str(error))
    if exp.variables and not any(x.nivel == ERROR for x in c):
        limite = float(config.get("llenado_maximo", 0.8)) * float(exp.capacidad_vaso_ml)
        minimos = {v.nombre: v.minimo for v in exp.variables}
        maximos = {v.nombre: v.maximo for v in exp.variables}
        if volumen_total(exp, gestor, minimos) > limite:
            err(f"Aun con los volúmenes mínimos se supera el máximo del vaso ({limite:.0f} mL = "
                f"{config.get('llenado_maximo', 0.8) * 100:.0f} % de {exp.capacidad_vaso_ml:g} mL).")
        elif volumen_total(exp, gestor, maximos) > limite:
            avi(f"Con los volúmenes máximos se superaría el límite del vaso ({limite:.0f} mL). "
                f"El programa descartará esas combinaciones.")
        if restricciones:
            import random
            azar = random.Random(0)
            posible = any(all(r(p) for r in restricciones) for p in (
                {v.nombre: azar.uniform(v.minimo, v.maximo) for v in exp.variables} for _ in range(3000)))
            if not posible:
                err("Las restricciones no dejan ninguna combinación posible de variables.")
    if len(c) == n_inicio:
        bien("Límites, restricciones y volumen del vaso son coherentes.")

    # 5. Conexión y estado de los módulos usados
    if not gestor.conectado():
        err("No hay conexión con el equipo. Vaya a Módulos y pulse Conectar.")
    else:
        fallas = 0
        for ident in sorted(usados):
            if ident not in gestor.modulos:
                continue
            ok, mensaje = gestor.pruebas.get(ident, (False, "Sin probar."))
            if not ok:
                fallas += 1
                err(f"{gestor.modulos[ident].etiqueta} no responde: {mensaje}")
            for aviso in gestor.modulos[ident].avisos():
                if "origen" in aviso and gestor.modulos[ident].TIPO == "brazo":
                    err(aviso)
                    fallas += 1
                else:
                    avi(aviso)
        if not fallas:
            bien(f"Conexión activa ({gestor.enlace.descripcion}) y módulos usados en condiciones.")
        if gestor.enlace.simulado:
            avi("Modo simulación: no se moverá ningún equipo y los resultados son inventados.")
        elif gestor.datos.get("sistema", {}).get("pin_parada") is None:
            avi("No hay botón de parada física declarado en la configuración. "
                "Se recomienda instalarlo antes de trabajar con reactivos.")

        if not gestor.enlace.simulado:
            for conflicto in gestor.conflictos_de_pines():
                err(conflicto)

    # 6. Reactivos
    faltan = [gestor.modulos[m].etiqueta for m in sorted(usados)
              if m in gestor.modulos and any(a.get("usa_reactivo") for a in gestor.modulos[m].acciones().values())
              and not str(exp.reactivos.get(m, "")).strip()]
    if faltan:
        avi(f"Falta indicar qué reactivo lleva: {', '.join(faltan)}.")
    for texto in incompatibilidades(exp.reactivos, config):
        avi(f"Reactivos incompatibles: {texto}")

    # 7. Historial
    if historial is not None:
        buenas, motivos = historial.usables(exp)
        if not buenas:
            err("El historial de esta reacción no tiene ningún experimento utilizable. "
                "Cargue al menos uno en la pantalla Historial.")
        else:
            bien(f"Historial: {len(buenas)} experimento(s) previo(s) utilizable(s).")
        if motivos:
            avi(f"{len(motivos)} experimento(s) del historial no se usarán porque les falta alguna variable.")
    return c


def hay_errores(chequeos: list[Chequeo]) -> bool:
    return any(x.nivel == ERROR for x in chequeos)
