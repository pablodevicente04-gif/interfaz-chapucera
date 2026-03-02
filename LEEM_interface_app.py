import serial
import serial.tools.list_ports
import time
import threading
import tkinter as tk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.pyplot as plt
from collections import deque
import sys

# ---------- CONFIGURACIÓN ----------
TIMEOUT = 1
MAX_PUNTOS = 200
SYNC_BYTE = b"\x01"
PACKET_SIZE = 28
COMANDO_IGNICION = b'\x04'
# ----------------------------------

# ---------- VARIABLES GLOBALES ----------
ser = None
leyendo = False
contador_paquetes = 0
ultimo_calculo_hz = None
hz_actual = 0.0

tiempos_hz = deque(maxlen=MAX_PUNTOS)
valores_hz = deque(maxlen=MAX_PUNTOS)
tiempo_inicio = None
# ----------------------------------------


def obtener_puertos():
    return [p.device for p in serial.tools.list_ports.comports()]


def refrescar_puertos():
    global puertos_actuales
    nuevos = obtener_puertos()
    if nuevos != puertos_actuales:
        puertos_actuales = nuevos
        menu = puerto_menu["menu"]
        menu.delete(0, "end")
        if puertos_actuales:
            for p in puertos_actuales:
                menu.add_command(label=p, command=lambda v=p: puerto_var.set(v))
            if puerto_var.get() not in puertos_actuales:
                puerto_var.set(puertos_actuales[0])
        else:
            menu.add_command(label="No hay puertos", command=lambda: puerto_var.set("No hay puertos"))
            puerto_var.set("No hay puertos")
    ventana.after(1000, refrescar_puertos)


def conectar():
    global ser, leyendo, tiempo_inicio, contador_paquetes, ultimo_calculo_hz, hz_actual

    puerto = puerto_var.get()
    if puerto == "No hay puertos":
        return

    try:
        ser = serial.Serial(puerto, int(baudrate_var.get()), timeout=TIMEOUT)
        time.sleep(1)

        leyendo = True
        tiempo_inicio = time.time()
        contador_paquetes = 0
        ultimo_calculo_hz = time.time()
        hz_actual = 0.0

        tiempos_hz.clear()
        valores_hz.clear()

        threading.Thread(target=leer_datos, daemon=True).start()
        actualizar_grafica()

        estado_label.config(text="Conectado", fg="#00FF88")
        btn_conectar.config(state="disabled")
        btn_desconectar.config(state="normal")

    except Exception as e:
        estado_label.config(text=f"Error: {e}", fg="red")


def desconectar():
    global ser, leyendo, contador_paquetes, ultimo_calculo_hz, hz_actual

    leyendo = False
    contador_paquetes = 0
    ultimo_calculo_hz = None
    hz_actual = 0.0

    if ser and ser.is_open:
        try:
            ser.close()
        except:
            pass
    ser = None

    estado_label.config(text="Desconectado", fg="red")
    hz_label.config(text="-- Hz")
    btn_conectar.config(state="normal")
    btn_desconectar.config(state="disabled")


def ignicion():
    if not ser or not ser.is_open:
        return
    threading.Thread(target=_enviar_ignicion, daemon=True).start()


def _enviar_ignicion():
    for _ in range(5):
        try:
            if ser and ser.is_open:
                ser.write(COMANDO_IGNICION)
            time.sleep(0.05)
        except Exception:
            break


def leer_datos():
    global contador_paquetes, ultimo_calculo_hz, hz_actual, leyendo

    while leyendo:
        try:
            if not ser or not ser.is_open:
                break

            b = ser.read(1)
            if b != SYNC_BYTE:
                continue

            payload = ser.read(PACKET_SIZE)
            if len(payload) != PACKET_SIZE:
                ser.reset_input_buffer()
                continue

            contador_paquetes += 1

            ahora = time.time()
            delta = ahora - ultimo_calculo_hz
            if delta >= 1.0:
                hz_actual = contador_paquetes / delta
                contador_paquetes = 0
                ultimo_calculo_hz = ahora

                t_rel = ahora - tiempo_inicio
                tiempos_hz.append(t_rel)
                valores_hz.append(hz_actual)

                hz_label.config(text=f"{hz_actual:.1f} Hz")

        except (serial.SerialException, OSError):
            ventana.after(0, desconectar)
            break


def actualizar_grafica():
    if leyendo:
        if len(tiempos_hz) >= 2:
            ax.clear()
            ax.plot(list(tiempos_hz), list(valores_hz),
                    color="#00FF88", linewidth=2, marker='o', markersize=3)
            ax.set_ylabel("Hz", color="white")
            ax.set_xlabel("Tiempo [s]", color="white")
            ax.set_title("Frecuencia de paquetes recibidos", color="white")
            ax.tick_params(colors="white")
            ax.spines['bottom'].set_color('#555555')
            ax.spines['top'].set_color('#555555')
            ax.spines['left'].set_color('#555555')
            ax.spines['right'].set_color('#555555')
            ax.set_facecolor("#2C2A36")
            ax.grid(True, color="#444444")
            fig.tight_layout()
            canvas.draw()

        ventana.after(1000, actualizar_grafica)


def cerrar():
    desconectar()
    ventana.destroy()
    sys.exit()


# ---------------- INTERFAZ ----------------
ventana = tk.Tk()
ventana.title("Hz Monitor")
ventana.geometry("700x500")
ventana.configure(bg="#15141B")

frame_left = tk.Frame(ventana, bg="#2C2A36", width=180)
frame_left.pack(side=tk.LEFT, fill=tk.Y, padx=10, pady=10)
frame_left.pack_propagate(False)

tk.Label(frame_left, text="Puerto COM", bg="#2C2A36", fg="white").pack(anchor="w", pady=(10, 2))
puerto_var = tk.StringVar()
puertos_actuales = obtener_puertos()
puerto_var.set(puertos_actuales[0] if puertos_actuales else "No hay puertos")
puerto_menu = tk.OptionMenu(frame_left, puerto_var,
                            *(puertos_actuales if puertos_actuales else ["No hay puertos"]))
puerto_menu.pack(fill="x", padx=5)

tk.Label(frame_left, text="Baudrate", bg="#2C2A36", fg="white").pack(anchor="w", pady=(10, 2))
baudrate_var = tk.StringVar(value="115200")
tk.Entry(frame_left, textvariable=baudrate_var, bg="#3C3A46", fg="white",
         insertbackground="white").pack(fill="x", padx=5)

tk.Frame(frame_left, height=2, bg="#555555").pack(fill="x", pady=15)

estado_label = tk.Label(frame_left, text="Desconectado", fg="red",
                        bg="#2C2A36", font=("Arial", 10, "bold"))
estado_label.pack(pady=5)

hz_label = tk.Label(frame_left, text="-- Hz", fg="#00FF88",
                    bg="#2C2A36", font=("Arial", 28, "bold"))
hz_label.pack(pady=15)

btn_conectar = tk.Button(frame_left, text="Conectar", command=conectar,
                         bg="#C88A53", fg="white", font=("Arial", 10, "bold"), width=14)
btn_conectar.pack(pady=4)

btn_desconectar = tk.Button(frame_left, text="Desconectar", command=desconectar,
                            bg="#C88A53", fg="white", font=("Arial", 10, "bold"),
                            width=14, state="disabled")
btn_desconectar.pack(pady=4)

tk.Frame(frame_left, height=2, bg="#555555").pack(fill="x", pady=5)

btn_ignicion = tk.Button(frame_left, text="🔥 IGNICIÓN", command=ignicion,
                         bg="#AA0000", fg="white", font=("Arial", 12, "bold"), width=14)
btn_ignicion.pack(pady=8)

frame_right = tk.Frame(ventana, bg="#15141B")
frame_right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=10, pady=10)

fig, ax = plt.subplots(figsize=(6, 5))
fig.patch.set_facecolor("#15141B")
ax.set_facecolor("#2C2A36")
canvas = FigureCanvasTkAgg(fig, master=frame_right)
canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

ventana.protocol("WM_DELETE_WINDOW", cerrar)
ventana.after(1000, refrescar_puertos)
ventana.mainloop()
