import serial
import serial.tools.list_ports
import time
import threading
import tkinter as tk
from tkinter import messagebox
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.pyplot as plt
from collections import deque
from queue import Queue, Empty
import struct
import sys
import csv
import os



# ---------- CONFIGURACIÓN ----------
TIMEOUT     = 1
MAX_PUNTOS  = 500
SYNC1       = 0x01
PACKET_SIZE = 28
CSV_FILE    = "calibracion.csv"
# ----------------------------------



# ---------- VARIABLES GLOBALES ----------
ser           = None
leyendo       = False
tiempo_inicio = None
data_queue    = Queue(maxsize=500)

tiempos_thrust = deque(maxlen=MAX_PUNTOS)
valores_thrust = deque(maxlen=MAX_PUNTOS)
ultimos_1000   = deque(maxlen=1000)
# ----------------------------------------



# ---------- BOTÓN COMPATIBLE CON MACOS ----------
def make_button(parent, text, command, bg="#C88A53", fg="white",
                font=("Arial", 10, "bold"), state="normal"):
    frame = tk.Frame(parent, bg=bg, cursor="hand2")
    label = tk.Label(frame, text=text, bg=bg, fg=fg, font=font,
                     anchor="center", pady=6)
    label.pack(fill="both")

    def _on_click(e):
        if frame._enabled:
            command()

    def _on_enter(e):
        if frame._enabled:
            r, g, b_ = ventana.winfo_rgb(bg)
            lighter = "#{:02x}{:02x}{:02x}".format(
                min(255, (r >> 8) + 25),
                min(255, (g >> 8) + 25),
                min(255, (b_ >> 8) + 25))
            frame.config(bg=lighter)
            label.config(bg=lighter)

    def _on_leave(e):
        c = bg if frame._enabled else "#555555"
        frame.config(bg=c)
        label.config(bg=c)

    def _set_state(s):
        frame._enabled = (s == "normal")
        c   = bg      if frame._enabled else "#555555"
        fg_ = fg      if frame._enabled else "#888888"
        cur = "hand2" if frame._enabled else "arrow"
        frame.config(bg=c, cursor=cur)
        label.config(bg=c, fg=fg_, cursor=cur)

    frame._enabled = True
    frame.config   = lambda **kw: (_set_state(kw["state"]) if "state" in kw else None)

    for widget in (frame, label):
        widget.bind("<Button-1>", _on_click)
        widget.bind("<Enter>",    _on_enter)
        widget.bind("<Leave>",    _on_leave)

    _set_state(state)
    return frame
# ------------------------------------------------



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
            menu.add_command(label="No hay puertos",
                             command=lambda: puerto_var.set("No hay puertos"))
            puerto_var.set("No hay puertos")
    ventana.after(1000, refrescar_puertos)



def conectar():
    global ser, leyendo, tiempo_inicio

    puerto = puerto_var.get()
    if puerto == "No hay puertos":
        return

    try:
        ser = serial.Serial(puerto, int(baudrate_var.get()), timeout=TIMEOUT)
        time.sleep(1)

        leyendo       = True
        tiempo_inicio = time.time()

        tiempos_thrust.clear()
        valores_thrust.clear()
        ultimos_1000.clear()

        while not data_queue.empty():
            try:
                data_queue.get_nowait()
            except Empty:
                break

        threading.Thread(target=leer_datos, daemon=True).start()
        ventana.after(20,   procesar_queue)
        ventana.after(1000, actualizar_grafica)

        estado_label.config(text="Conectado", fg="#00FF88")
        btn_conectar.config(state="disabled")
        btn_desconectar.config(state="normal")

    except Exception as e:
        estado_label.config(text=f"Error: {e}", fg="red")



def desconectar():
    global ser, leyendo

    leyendo = False

    if ser and ser.is_open:
        try:
            ser.close()
        except:
            pass
    ser = None

    estado_label.config(text="Desconectado", fg="red")
    thrust_label.config(text="-- N")
    avg_label.config(text="Prom(1000): -- N")
    btn_conectar.config(state="normal")
    btn_desconectar.config(state="disabled")



def leer_datos():
    global leyendo

    while leyendo:
        # Wait for first sync byte
        try:
            b = ser.read(1)
        except (serial.SerialException, OSError):
            data_queue.put({"tipo": "error"})
            break

        if len(b) != 1 or b[0] != SYNC1:
            continue

        # Wait for second sync byte

        # Read payload
        try:
            payload = ser.read(PACKET_SIZE)
        except (serial.SerialException, OSError):
            data_queue.put({"tipo": "error"})
            break

        if len(payload) != PACKET_SIZE:
            continue

        thrust = struct.unpack("<h", payload[4:6])[0] / 100.0
        ts     = time.time()

        try:
            data_queue.put_nowait({"tipo": "datos", "thrust": thrust, "ts": ts})
        except:
            pass



def procesar_queue():
    if not leyendo:
        return

    procesados = 0
    while procesados < 20:
        try:
            paquete = data_queue.get_nowait()
        except Empty:
            break

        if paquete["tipo"] == "error":
            ventana.after(0, desconectar)
            return

        thrust = paquete["thrust"]
        t_rel  = paquete["ts"] - tiempo_inicio

        tiempos_thrust.append(t_rel)
        valores_thrust.append(thrust)
        ultimos_1000.append(thrust)

        thrust_label.config(text=f"{thrust:.2f} N")

        n = len(ultimos_1000)
        if n > 0:
            avg = sum(ultimos_1000) / n
            avg_label.config(text=f"Prom({n}/1000): {avg:.2f} N")

        procesados += 1

    ventana.after(20, procesar_queue)



def guardar_punto():
    if not ultimos_1000:
        messagebox.showwarning("Sin datos", "Todavía no hay datos suficientes.")
        return

    try:
        peso_kg = float(peso_var.get())
    except ValueError:
        messagebox.showerror("Error", "Introduce un peso válido en kg.")
        return

    n     = len(ultimos_1000)
    avg_N = sum(ultimos_1000) / n
    ts    = time.strftime("%Y-%m-%d %H:%M:%S")

    escribir_header = not os.path.exists(CSV_FILE)
    with open(CSV_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        if escribir_header:
            writer.writerow(["timestamp", "peso_kg", "thrust_prom_N", "n_muestras"])
        writer.writerow([ts, peso_kg, f"{avg_N:.4f}", n])

    messagebox.showinfo(
        "Guardado",
        f"Punto guardado:\n  Peso: {peso_kg} kg\n  Thrust prom: {avg_N:.2f} N\n  Muestras: {n}"
    )



def actualizar_grafica():
    if not leyendo:
        return

    if len(tiempos_thrust) >= 2:
        t   = list(tiempos_thrust)
        th  = list(valores_thrust)
        avg = sum(ultimos_1000) / len(ultimos_1000) if ultimos_1000 else 0.0

        ax.clear()
        ax.plot(t, th, color="#C88A53", linewidth=2, label="Thrust")
        ax.axhline(avg, color="#00FF88", linewidth=1.4,
                   linestyle="--", label=f"Prom(1000): {avg:.2f} N")

        ax.set_ylabel("Thrust [N]",          color="white")
        ax.set_xlabel("Tiempo [s]",           color="white")
        ax.set_title("Thrust en tiempo real", color="white")
        ax.tick_params(colors="white")
        ax.spines['bottom'].set_color('#555555')
        ax.spines['top'].set_color('#555555')
        ax.spines['left'].set_color('#555555')
        ax.spines['right'].set_color('#555555')
        ax.set_facecolor("#2C2A36")
        ax.grid(True, color="#444444")
        ax.legend(facecolor="#2C2A36", labelcolor="white", fontsize=9)
        fig.tight_layout()
        canvas.draw()

    ventana.after(1000, actualizar_grafica)



def cerrar():
    desconectar()
    ventana.destroy()
    sys.exit()



# ---------------- INTERFAZ ----------------
ventana = tk.Tk()
ventana.title("Thrust Calibration")
ventana.geometry("700x520")
ventana.configure(bg="#15141B")

frame_left = tk.Frame(ventana, bg="#2C2A36", width=180)
frame_left.pack(side=tk.LEFT, fill=tk.Y, padx=10, pady=10)
frame_left.pack_propagate(False)

tk.Label(frame_left, text="Puerto COM", bg="#2C2A36", fg="white").pack(anchor="w", pady=(10, 2))
puerto_var       = tk.StringVar()
puertos_actuales = obtener_puertos()
puerto_var.set(puertos_actuales[0] if puertos_actuales else "No hay puertos")
puerto_menu = tk.OptionMenu(frame_left, puerto_var,
                            *(puertos_actuales if puertos_actuales else ["No hay puertos"]))
puerto_menu.pack(fill="x", padx=5)

tk.Label(frame_left, text="Baudrate", bg="#2C2A36", fg="white").pack(anchor="w", pady=(10, 2))
baudrate_var = tk.StringVar(value="115200")
tk.Entry(frame_left, textvariable=baudrate_var, bg="#3C3A46", fg="white",
         insertbackground="white").pack(fill="x", padx=5)

tk.Frame(frame_left, height=2, bg="#555555").pack(fill="x", pady=10)

estado_label = tk.Label(frame_left, text="Desconectado", fg="red",
                        bg="#2C2A36", font=("Arial", 10, "bold"))
estado_label.pack(pady=5)

thrust_label = tk.Label(frame_left, text="-- N", fg="#C88A53",
                        bg="#2C2A36", font=("Arial", 28, "bold"))
thrust_label.pack(pady=(10, 2))

avg_label = tk.Label(frame_left, text="Prom(1000): -- N", fg="#00FF88",
                     bg="#2C2A36", font=("Arial", 11, "bold"))
avg_label.pack(pady=(0, 15))

tk.Frame(frame_left, height=2, bg="#555555").pack(fill="x", pady=5)

tk.Label(frame_left, text="Peso aplicado (kg)", bg="#2C2A36",
         fg="#AAAAAA", font=("Arial", 9)).pack(anchor="w", padx=5, pady=(6, 2))
peso_var = tk.StringVar(value="0.0")
tk.Entry(frame_left, textvariable=peso_var, bg="#3C3A46", fg="white",
         insertbackground="white", font=("Arial", 12)).pack(fill="x", padx=5)

btn_guardar = make_button(frame_left, "💾 Guardar punto", guardar_punto,
                          bg="#4A90D9", fg="white", font=("Arial", 10, "bold"))
btn_guardar.pack(pady=8, fill="x", padx=5)

tk.Frame(frame_left, height=2, bg="#555555").pack(fill="x", pady=5)

btn_conectar = make_button(frame_left, "Conectar", conectar,
                           bg="#C88A53", fg="white", font=("Arial", 10, "bold"))
btn_conectar.pack(pady=4, fill="x", padx=5)

btn_desconectar = make_button(frame_left, "Desconectar", desconectar,
                              bg="#C88A53", fg="white", font=("Arial", 10, "bold"),
                              state="disabled")
btn_desconectar.pack(pady=4, fill="x", padx=5)

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
