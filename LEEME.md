# SDL — Laboratorio autónomo · versión 1.4

Programa de control del Self-Driving Laboratory. Recibe la definición de un experimento, revisa que el equipo pueda hacerlo, analiza los experimentos anteriores y decide el próximo con optimización bayesiana; lo ejecuta con el robot, registra el resultado y repite hasta cumplir las metas, llegar al máximo de experimentos o hasta que el químico lo dé por terminado.

- **PC:** Python (NumPy, SciPy, scikit-learn, NiceGUI, pyserial, PyYAML, Matplotlib, ReportLab).
- **ESP32-S2:** MicroPython, conectado por USB.
- **Uso:** todo desde la interfaz. Los químicos no editan archivos ni escriben código.

## Cambios de la versión 1.4

- **Módulo nuevo: «Agitador (NEMA17)».** Agitador con motor paso a paso y driver DRV8825, que gira siempre en el mismo sentido (no tiene opción de dirección). Convive con el agitador de motor de corriente continua, que no cambia. Tiene las mismas acciones (agitar, encender, apagar) y la velocidad se da en rpm. Ver «Agitador con NEMA17».
- **Hay que actualizar el ESP32 (solo si usa el agitador NEMA17):** driver nuevo `motor_paso.py` y `main.py`. Pasos en «Actualizar el ESP32».

## Cambios de la versión 1.3

- **El caudal es una función continua de la apertura.** Con las aperturas calibradas se arma una curva caudal-apertura; al pedir un caudal, el servo va a la apertura que la curva indica, aunque no sea una de las calibradas. Ver «Regular el caudal». No cambia nada en el ESP32 respecto de la 1.2.

## Cambios de la versión 1.2

- **Apertura parcial del robinete para regular el caudal.** Cada apertura (en % del recorrido del servo) se calibra por separado. Al dosificar se puede pedir un caudal, fijo o como variable a optimizar, y el servo abre solo hasta la apertura calibrada que más se acerca. Ver «Regular el caudal».
- **Variable nueva con historial anterior.** Al agregar una variable se puede anotar el valor que tuvo en los experimentos ya hechos, para que sigan sirviendo.
- **Hay que actualizar el ESP32:** `mpremote cp drivers/servo_valvula.py :drivers/servo_valvula.py` y `mpremote cp main.py :main.py`. Si el ESP32 queda con el driver viejo, el programa se niega a usar aperturas parciales (el robinete abierto del todo sigue funcionando).

## Cambios de la versión 1.1

- **Bureta: corregido el error de «no hay reactivo suficiente».** El programa pedía la *lectura de la escala* (donde 0 es «llena»), así que al escribir 25 entendía «vacía» y repetía el pedido. Ahora pregunta siempre **cuántos mL de reactivo hay en la bureta** (llena = 25), propone 25 por defecto y, al pedir una recarga, no acepta un valor menor que la dosis que falta entregar. Lo guardado por la versión anterior se convierte solo.
- **Calibración a mano de la bureta.** En *Equipo → Calibrar* se escribe el volumen que salió y el tiempo que tardó; el programa calcula el caudal y muestra cuánto tiempo abrirá el robinete para cada dosis. Sigue estando la opción de que el programa abra el robinete un tiempo fijo.
- **Sensor de pH con temperatura** como módulo nuevo (*Equipo → Agregar módulo → Sensor de pH*), con calibración de dos buffers. Sus mediciones aparecen como objetivo automático y como dato para anotar en cada experimento.

**Para actualizar:** descomprimir sobre la carpeta anterior y aceptar reemplazar. El paquete no trae las carpetas `config/` ni `datos/`, así que no pisa la instalación, las calibraciones ni los historiales. En el ESP32 hay que copiar el driver nuevo: `mpremote cp drivers/sensor_ph.py :drivers/sensor_ph.py`.

## Estado de esta versión

| Parte | Estado |
|---|---|
| Optimizador, validación, historial, motor de campañas, informe | Probado con pruebas automáticas (`pruebas/`) |
| Interfaz | Probada en simulación con un navegador: campaña completa, preguntas, parada y rearme |
| Protocolo PC ↔ ESP32 | Probado conectando los módulos reales de la PC con el código real del firmware, con pines simulados |
| Firmware sobre el ESP32-S2 real | **Sin probar.** No tuve acceso al hardware (incluye el driver del NEMA17). Ver «Primera puesta en marcha» |
| Módulo de cámara | Versión básica, desactivada. Falta unirla con `detector.py` |

## 1. Instalación y arranque

1. Instalar Python 3.10 o más nuevo.
2. Windows: doble clic en `iniciar.bat`. La primera vez crea un entorno e instala las librerías (unos minutos, con internet). Linux/macOS: `./iniciar.sh`.
3. Se abre el navegador en `http://127.0.0.1:8080`. El programa sigue corriendo aunque se cierre la pestaña; para cerrarlo, Ctrl+C en la ventana negra.

Arranca en **modo simulación**, con un experimento de ejemplo (síntesis de magnetita) cuyos datos previos son inventados. Para verlo funcionar solo: *Ejecución → Demostración automática → Iniciar campaña*.

## 2. Uso: los cinco pasos

1. **Equipo.** Elegir simulación o equipo real, conectar y ver qué módulos responden. Desactivar los que no estén colocados. Desde acá se calibran buretas y bomba, se usa cualquier módulo a mano y se enseñan las estaciones del brazo.
2. **Experimento.** Variables a ajustar con sus límites, objetivos (aumentar, reducir o llevar a un valor, con meta opcional), protocolo paso a paso, condiciones entre variables, reactivos y máximo de experimentos. Cada cambio se guarda solo y la sección *Revisión* muestra si falta algo.
3. **Historial.** Experimentos ya hechos sobre la reacción. Hace falta al menos uno. Se cargan a mano o desde una planilla.
4. **Ejecución.** Verificación previa, lista de seguridad y campaña en vivo: propuesta, pasos, preguntas al usuario, gráficos y bitácora.
5. **Informe.** Mejores resultados, frente de Pareto, gráficos, tabla completa, PDF y exportación a Excel.

### Qué puede ser una variable

| Tipo | Ejemplo | Cómo se ejecuta |
|---|---|---|
| Automática | Volumen de la bureta 1, velocidad del agitador | La ajusta el módulo |
| Tiempo de espera | Tiempo de reacción | El programa espera |
| Manual | Temperatura de la placa, masa de un sólido | El programa pide el ajuste y espera la confirmación |

Si una variable necesita un módulo desactivado o que no responde, o sus límites exceden lo que el módulo admite, la verificación lo marca como error y la campaña **no arranca**.

### Pasos del protocolo

Acción de un módulo · esperar · pedirle algo al usuario y esperar confirmación (por ejemplo, agregar un reactivo) · ajuste manual de una variable · medir un objetivo (automático o ingresado por el usuario).

## 3. Cómo decide el próximo experimento

1. **Exploración.** Con pocos datos, propone puntos bien repartidos (secuencia de Sobol, lo más lejos posible de lo ya ensayado). Cantidad: cerca del 30 % del máximo de experimentos, con piso de 5 y tope de 2 por variable; los previos cuentan.
2. **Optimización (ParEGO).** En cada vuelta sortea una prioridad entre los objetivos, los combina en un solo número (Chebyshev aumentado), ajusta un proceso gaussiano **con ruido** y elige el punto de mayor mejora esperada entre miles de candidatos que respetan límites, resolución, condiciones y capacidad del vaso. Al variar la prioridad en cada vuelta, recorre el frente de Pareto.
3. **Reacción que no ocurre.** El químico lo indica; el experimento queda como «sin reacción» y entra al modelo con un costo peor que el peor observado.
4. **Fin de campaña.** Metas cumplidas (ofrece finalizar, repetir para confirmar o seguir), máximo de experimentos, «Estoy conforme: finalizar», aviso opcional por falta de mejora, o parada de emergencia.

Con `pruebas/prueba_optimizador.py` se comprueba que supera a elegir experimentos al azar con 1, 2 y 3 objetivos.

## 4. Protocolo de seguridad

| Capa | Dónde | Qué hace |
|---|---|---|
| 0 | Cableado | Botón de parada que corta la potencia de los actuadores. **Hay que instalarlo**; no depende de ningún programa |
| 1 | Firmware | Tiempo máximo de válvula abierta y de motor encendido, recorrido del brazo, parada enclavada, y estado seguro si la PC deja de responder (latido, 5 s) |
| 2 | Módulos (PC) | Cada orden se compara con los límites absolutos del equipo |
| 3 | Experimento | Límites del químico, condiciones entre variables y llenado máximo del vaso (80 %). Toda propuesta se revisa antes de ejecutarse |
| 4 | Personas | Lista previa obligatoria, confirmación de reactivos, aprobación de cada propuesta (modo supervisado), y espera máxima (15 min) tras la cual todo queda seguro |

Además:

- **Parada de emergencia** siempre visible. Cierra válvulas, apaga motores, deja el brazo quieto y anota el experimento como abortado. Para seguir hay que **rearmar** a mano.
- **Estado seguro:** válvulas cerradas, bomba y agitador apagados, brazo quieto y sosteniendo la carga (soltarlo sería peor).
- **Experimento interrumpido** (parada, error, corte de luz): queda como abortado y no se usa para optimizar.
- **Reactivos:** aviso si dos reactivos cargados figuran en una lista de combinaciones peligrosas (`config/seguridad.yaml`). Es orientativa; no reemplaza el criterio del químico.
- **Bitácora:** todo queda en `datos/bitacora.txt` con fecha y hora.

Lo que el programa no puede resolver:

- Un servo sin energía queda donde estaba. Si se corta la alimentación con un robinete abierto, sigue abierto.
- La pausa actúa entre pasos y no apaga un agitador ya encendido. Para cortar todo, usar la parada.
- El agitador y la bomba se apagan solos a los 180 s (límite puesto por el motor 895). Si un protocolo necesita agitar más tiempo, subir «Marcha continua máxima» en la configuración del módulo solo si el motor lo soporta.

## 5. Firmware del ESP32-S2

### Cargarlo

```
pip install mpremote
cd firmware
mpremote mkdir :drivers
mpremote cp drivers/__init__.py :drivers/__init__.py
mpremote cp drivers/servo_valvula.py :drivers/servo_valvula.py
mpremote cp drivers/motor_dc.py :drivers/motor_dc.py
mpremote cp drivers/motor_paso.py :drivers/motor_paso.py
mpremote cp drivers/brazo.py :drivers/brazo.py
mpremote cp drivers/ds18b20.py :drivers/ds18b20.py
mpremote cp drivers/sensor_ph.py :drivers/sensor_ph.py
mpremote cp main.py :main.py
mpremote reset
```

Los pines **no** están en el firmware: los manda la PC al conectar, según la configuración de cada módulo (*Equipo → Configurar → Instalación*).

### Pines por defecto

| Función | GPIO |
|---|---|
| Brazo: STEP de cintura, hombro, codo, muñeca | 4, 6, 8, 10 |
| Brazo: DIR de cintura, hombro, codo, muñeca | 5, 7, 9, 11 |
| Brazo: ENABLE común de los DRV8825 | 12 |
| Servo de bureta 1 / bureta 2 / pinza | 13 / 14 / 15 |
| Agitador de corriente continua (PWM) | 16 |
| Agitador NEMA17: STEP / ENABLE (DIR va a GND, no al ESP32) | 17 / 18 |
| Bomba: PWM adelante / atrás | 33 / 34 |
| DS18B20 (datos) | 37 |
| Sensor de pH: señal de pH / temperatura | 1 / 2 |
| Botón de parada (normal cerrado a GND) | sin asignar; sugerido 21 |
| Habilitación de puentes H | sin asignar; sugerido 35 |

Con un BTS7960: RPWM y LPWM van a los pines «adelante» y «atrás»; R_EN y L_EN, al pin de habilitación (o a 3,3 V).

### Primera puesta en marcha (sin reactivos)

1. Con solo el ESP32 conectado por USB: *Equipo → Equipo real → Conectar*. Debe aparecer la versión del firmware. Si no responde, es el primer punto a revisar: el firmware lee las órdenes por la misma conexión serie que usa `mpremote`.
2. Conectar un módulo por vez y probarlo con *Usar manualmente*.
3. Calibrar cada bureta y la bomba con agua.
4. Brazo: llevarlo a mano a la postura de referencia, *Fijar origen*, moverlo de a pocos grados y guardar cada estación.
5. Probar la parada (pantalla y botón físico) y desconectar el USB con el agitador encendido: debe apagarse solo en 5 s.
6. Agitador NEMA17: probarlo primero sin la hélice, con *Usar manualmente → Agitar* a 60 rpm durante 5 s. Debe arrancar suave, girar parejo y quedar libre al terminar. Si vibra o zumba sin girar, bajar la aceleración o revisar el orden de los cables de las bobinas; si se calienta, bajar el Vref del DRV8825. Este driver genera los pulsos con el PWM por hardware del ESP32 y es lo que más conviene verificar en el equipo real (el ESP32-S2 tiene 8 canales PWM y se usan 7 con todos los módulos instalados).
7. Recién entonces poner `USAR_VIGILANTE = True` en `main.py` y volver a cargarlo.

## 6. Bureta y sensor de pH

### Calibrar una bureta a mano

1. Llenar la bureta y poner una probeta debajo.
2. *Equipo → Bureta → Usar manualmente → Abrir el robinete*, cronometrar, y *Cerrar el robinete*. Conviene abrirlo siempre con el servo, para que la apertura sea la misma que usará al dosificar.
3. *Equipo → Bureta → Calibrar*: escribir cuánto había al empezar, cuánto salió y cuánto tardó.
4. El programa muestra el caudal medio, el caudal con la bureta llena y casi vacía, y el tiempo de apertura para 1, 5, 10 y 20 mL. Al guardar, usa ese caudal para calcular el tiempo de cada dosis según el nivel que tenga la bureta en ese momento.

Una sola medición por apertura alcanza; repetirla con otro volumen sirve para comprobar que el modelo acierta.

### Regular el caudal (apertura parcial)

El servo puede abrir el robinete solo en parte. La **apertura** se expresa en % del recorrido entre cerrado y abierto del todo (con los ángulos por defecto, 40 % son 36°).

1. Calibrar primero el 100 %. Después, cada apertura parcial que se quiera usar (por ejemplo 60 % y 40 %), con el mismo procedimiento y escribiendo la apertura en el primer campo. Para abrir a mano en una apertura: *Usar manualmente → Abrir el robinete → Apertura*.
2. La lista de aperturas calibradas, con su caudal, se ve en la fila de la bureta y al abrir *Calibrar*.
3. Para usarla hay tres formas:
   - **En un paso:** al agregar «Dosificar un volumen», completar *Caudal (opcional)*.
   - **Como variable a optimizar:** *Agregar variable → Bureta: caudal*. Aparece cuando hay al menos dos aperturas calibradas. La velocidad de agregado pasa a ser algo que el optimizador explora.
   - **Por defecto para la bureta:** *Configurar → Caudal habitual al dosificar*. Vacío = abierto del todo.

Cómo decide: con los puntos calibrados arma una **curva caudal-apertura**. Entre dos puntos vecinos interpola en línea recta el logaritmo del caudal (es decir, una exponencial por tramos), porque el caudal de un robinete crece de forma brusca al abrirlo y una recta común lo representaría mal. Para un caudal pedido busca en la curva la apertura que lo da, la redondea a 0,5 % y calcula el tiempo de la dosis con el caudal de esa apertura.

- La curva pasa exactamente por los puntos medidos.
- No se extiende fuera de lo calibrado: un caudal menor que el de la apertura más chica, o mayor que el del 100 %, se rechaza.
- Entre puntos es una **estimación**. Con dos puntos alcanza para funcionar; con cuatro o más (por ejemplo 100, 70, 50 y 35 %) es bastante más confiable.
- **Para comprobarla:** al calibrar una apertura nueva, el programa muestra qué caudal preveía la curva para esa apertura y cuánto difiere de lo medido. Si la diferencia es chica, la curva es buena en esa zona; si es grande, conviene agregar ese punto (se agrega al guardar).
- Si una apertura menor da más caudal que una mayor, hay una medición mal: la curva se desactiva sola y avisa.
- Para volver al comportamiento anterior (usar solo aperturas calibradas): *Configurar → Usar la curva caudal-apertura*.

A tener en cuenta:

- El caudal de una misma apertura baja con el nivel de la bureta. El «caudal» de cada apertura es el que da con la bureta llena.
- Cuanto más chica la apertura, peor se repite (juego del servo, roce del robinete). Conviene comprobar cada apertura dosificando dos o tres veces el mismo volumen.
- Las dosis lentas duran mucho: 20 mL a 0,1 mL/s son casi 4 minutos. El agitador se apaga solo a los 180 s; si tiene que agitar durante toda la dosis, hay que subir su «Marcha continua máxima».
- Si se cambian los ángulos «cerrado» o «abierto» del servo, hay que volver a calibrar todas las aperturas.

### Sensor de pH

- **Qué supone el módulo:** una sonda con placa amplificadora de salida analógica (tipo PH-4502C). Si el sensor es de otro tipo (I2C, por ejemplo), hay que adaptar el driver.
- **Cableado:** la señal de pH va a un pin entre GPIO 1 y 10 (por defecto el 1). El ESP32-S2 mide bien hasta unos 2,5 V: si la placa se alimenta con 5 V, poner un **divisor de tensión** (por ejemplo 10 kΩ y 20 kΩ) entre la salida y el pin.
- **Temperatura:** en *Configurar → Lectura de temperatura* elegir `ds18b20` (sonda digital), `analogica` (salida de tensión de la placa, con su señal a 0 °C y por grado) o `ninguna`.
- **Calibración:** *Equipo → Sensor de pH → Calibrar*, con dos buffers (7 y 4, o 7 y 10). Sin calibrar, el programa avisa antes de cada campaña.
- **Uso:** al agregar un objetivo, en «¿Cómo se mide?» aparece «Automático — Sensor de pH». También se puede anotar el pH o la temperatura en cada experimento sin optimizarlos.
- El pH no se corrige por temperatura.

### Agitador con NEMA17

*Equipo → Agregar módulo → Agitador (NEMA17)*, después **Volver a conectar**. Puede tener los dos agitadores instalados a la vez; se usa el que se elija en cada paso.

- **Conexión del DRV8825:** STEP al GPIO 17, ENABLE al GPIO 18, y el pin **DIR a GND** (no va al ESP32). Si la hélice gira al revés, se pasa el cable de DIR de GND a 3,3 V. Los micropasos se fijan con M0, M1 y M2 (el ESP32 no los controla); por defecto el programa supone 16, que en el DRV8825 es **solo M2 a 3,3 V, con M0 y M1 a GND**. Si se cablea otra combinación, hay que cambiar «Micropasos» en la configuración del módulo, porque de eso depende la velocidad real en rpm. RESET y SLEEP unidos entre sí; capacitor de 100 µF entre VMOT y GND, cerca del driver.
- **Velocidad en rpm.** El programa la convierte en pasos por segundo según los pasos por vuelta (200) y los micropasos (16): 300 rpm son 16 000 pasos por segundo. El límite práctico de un NEMA17 está en unos 20 000 pasos por segundo; si la velocidad máxima lo supera, el módulo avisa.
- **Arranque con rampa.** El motor arranca despacio y acelera hasta la velocidad pedida (150 rpm/s por defecto); así no pierde pasos con la hélice dentro del líquido. Al apagarse o ante una parada se detiene de inmediato y se le corta la corriente (queda libre; no sostiene la varilla).
- **Corriente del driver:** se regula con el potenciómetro del DRV8825 (Vref). Para un agitador alcanza con poco; la hélice y la varilla casi no cargan al motor y así se evita que el motor y el driver se calienten durante varias horas de espera.
- **Marcha máxima:** 300 s por defecto (se corta solo), pensada para mezclas de hasta 5 minutos.
- El archivo de un experimento que usa el agitador de corriente continua no sirve tal cual con el NEMA17: cambia la unidad de la velocidad (% frente a rpm), así que hay que elegir el módulo de nuevo en el paso.

### Agregar otro módulo nuevo

Son dos archivos; el resto del programa no se toca.

1. **PC:** copiar `sdl/modulos/_plantilla.py` con otro nombre y completar tipo, configuración, mediciones y `medir()`. `sensor_ph.py` sirve de ejemplo completo.
2. **ESP32:** copiar `firmware/drivers/_plantilla.py` con el nombre del driver, completarlo y cargarlo con `mpremote cp`.
3. En *Equipo → Agregar módulo* elegir el tipo nuevo y conectar.

### Actualizar el ESP32

Cuando una versión trae firmware nuevo, el programa lo avisa al conectar: dice que el ESP32 no tiene el driver necesario («falta copiar firmware/drivers/…»). Para la versión 1.4:

1. Cerrar el programa SDL (así `mpremote` puede usar el puerto) y dejar el ESP32 conectado por USB.
2. Abrir una terminal en la carpeta `firmware` de la versión nueva.
3. Copiar los dos archivos:
   ```
   mpremote cp drivers/motor_paso.py :drivers/motor_paso.py
   mpremote cp main.py :main.py
   mpremote reset
   ```
4. Abrir el programa, *Equipo → Volver a conectar*. Debe aparecer «agitador_paso» en la lista de módulos y responder «Motor detenido y sin corriente».

Los otros drivers (bureta, bomba, brazo, pH, temperatura) no cambiaron: no hace falta volver a copiarlos. Si algo sale mal, `mpremote ls :drivers` muestra qué hay en el ESP32.

## 7. Archivos

```
iniciar.py / iniciar.bat     abre el programa
config/modulos.yaml          módulos instalados, conexión y pines (lo escribe la pantalla Equipo)
config/seguridad.yaml        tiempos de espera, lista previa, combinaciones peligrosas
datos/experimentos/*.yaml    un archivo por experimento (lo escribe la pantalla Experimento)
datos/reacciones/<reacción>/historial.csv     un experimento por fila
datos/reacciones/<reacción>/informes/*.pdf    informes generados
datos/bitacora.txt           registro de todo lo que hizo el programa
sdl/optimizador.py           optimización bayesiana multiobjetivo
sdl/motor.py                 bucle proponer → ejecutar → medir → aprender
sdl/seguridad.py             verificación previa y revisión de cada propuesta
sdl/modulos/                 un archivo por tipo de módulo
sdl/comunicacion.py          enlace USB y simulador
sdl/interfaz/                pantallas
firmware/                    MicroPython para el ESP32-S2
pruebas/                     pruebas automáticas:  python pruebas/ejecutar_todas.py
```

Formatos: YAML para experimentos y configuración (legible y con estructura); CSV con `;` para el historial (se abre con Excel). Los experimentos que comparten el nombre de **reacción** comparten historial; si cambian reactivos o condiciones fijas, conviene usar otro nombre de reacción.

## 8. Limitaciones conocidas

- **Dosificación por tiempo.** La bureta entrega por tiempo de apertura con un modelo de caudal que baja con el nivel (Torricelli). Sin calibrar, los volúmenes son aproximados. El error real hay que medirlo.
- **pH como variable a ajustar.** El pH se puede medir y optimizar como objetivo, pero todavía no existe la acción «dosificar hasta llegar a un pH».
- **Brazo.** Mueve una articulación por vez entre estaciones enseñadas a mano; no tiene cinemática inversa ni finales de carrera. Después de cada encendido, o de una parada en pleno movimiento, hay que fijar el origen otra vez.
- **Variables.** Solo numéricas (continuas o con resolución). No hay variables de categoría (tipo de reactivo).
- **Multi-fidelidad.** La idea de medir una propiedad temprana A y una final B todavía no se aprovecha: cada objetivo se modela por separado.
- **Un solo vaso.** El protocolo asume una reacción por vez en un vaso; el cambio y lavado del vaso es un paso manual.
