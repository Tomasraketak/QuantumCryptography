"""QKD demonstrátor BB84 - jedno okno pro Alici i Boba.

Spuštění:  python qkd_gui.py
Obě Arduina připoj USB do jednoho PC, vyber porty a dej Připojit.
Bez hardwaru zaškrtni "Simulace" (a případně "Eve poslouchá").
"""
import queue
import threading
import tkinter as tk
from tkinter import filedialog, ttk

import numpy as np
from PIL import Image, ImageTk

import qcrypt
from qkd_core import KEY_BITS, N_QUBITS, QBER_LIMIT, Round, SerialBackend, SimBackend, parse_line

BASIS = ["HV  (+)", "DA  (×)"]
POL = {(0, 0): "↔  H", (0, 1): "↕  V", (1, 0): "⤢  D", (1, 1): "⤡  A"}
HWP = {(0, 0): "45°", (0, 1): "0°", (1, 0): "-22.5°", (1, 1): "+22.5°"}
DET = {0: "detektor 0 → 0", 1: "detektor 1 → 1", None: "nic (ztráta)"}
PREVIEW = 200

INTRO = ("1) Připoj obě Arduina (nebo zapni simulaci) a stiskni START.\n"
         "Alice náhodně volí bit a bázi a natáčí HWP. Bob náhodně volí svoji bázi a měří, "
         "na kterém detektoru se laser objeví. Kde se báze shodují, mají oba stejný bit.")


class App:
    def __init__(self, root):
        self.root = root
        root.title("Kvantová distribuce klíče BB84 – Alice & Bob")
        self.events = queue.Queue()
        self.backend = None
        self.round = None
        self.key = None
        self.image = None
        self.sending = False
        self.parser = qcrypt.FrameParser()
        self._build()
        self.root.after(50, self._poll)

    # ------------------------------------------------------------ layout
    def _build(self):
        style = ttk.Style()
        style.configure("Big.TLabel", font=("Segoe UI", 12))
        style.configure("Key.TLabel", font=("Consolas", 16, "bold"))
        style.configure("H.TLabelframe.Label", font=("Segoe UI", 11, "bold"))

        top = ttk.Frame(self.root, padding=6)
        top.pack(fill="x")
        ports = self._ports()
        ttk.Label(top, text="Alice port:").pack(side="left")
        self.alice_port = ttk.Combobox(top, values=ports, width=12)
        self.alice_port.pack(side="left", padx=4)
        ttk.Label(top, text="Bob port:").pack(side="left")
        self.bob_port = ttk.Combobox(top, values=ports, width=12)
        self.bob_port.pack(side="left", padx=4)
        if len(ports) >= 2:
            self.alice_port.set(ports[0]); self.bob_port.set(ports[1])
        self.sim = tk.BooleanVar(value=not ports)
        ttk.Checkbutton(top, text="Simulace (bez HW)", variable=self.sim).pack(side="left", padx=6)
        self.eve = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text="Eve poslouchá (jen simulace)", variable=self.eve).pack(side="left")
        self.btn_conn = ttk.Button(top, text="Připojit", command=self.connect)
        self.btn_conn.pack(side="left", padx=6)
        self.btn_start = ttk.Button(top, text="▶ START – vytvořit klíč", command=self.start, state="disabled")
        self.btn_start.pack(side="left")
        self.status = ttk.Label(top, text="Nepřipojeno")
        self.status.pack(side="left", padx=10)

        self.explain = ttk.Label(self.root, text=INTRO, style="Big.TLabel", wraplength=1150,
                                 padding=8, background="#fff8dc", relief="groove")
        self.explain.pack(fill="x", padx=6)

        mid = ttk.Frame(self.root, padding=6)
        mid.pack(fill="both", expand=True)

        # --- tabulka qubitu
        tf = ttk.LabelFrame(mid, text="Kvantový kanál – qubit po qubitu", style="H.TLabelframe")
        cols = ("i", "abase", "abit", "hwp", "pol", "bbase", "bdet", "match", "role")
        heads = ("#", "Alice báze", "Alice bit", "Alice HWP", "polarizace", "Bob báze",
                 "Bob naměřil", "báze stejné?", "použití")
        widths = (35, 75, 60, 70, 75, 75, 115, 85, 140)
        ttk.Label(tf, text="zelená = bit klíče   modrá = testovací bit (veřejně porovnán)   "
                           "červená = chyba   šedá = jiné báze / ztráta → zahozeno").pack(side="bottom", anchor="w")
        self.tree = ttk.Treeview(tf, columns=cols, show="headings", height=18)
        for c, h, w in zip(cols, heads, widths):
            self.tree.heading(c, text=h)
            self.tree.column(c, width=w, anchor="center")
        sb = ttk.Scrollbar(tf, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        for tag, col in (("pending", "#ffffff"), ("drop", "#e6e6e6"), ("key", "#c8f7c5"),
                         ("test", "#cfe3ff"), ("err", "#ffb3b3"), ("lost", "#f0f0f0")):
            self.tree.tag_configure(tag, background=col)

        # --- vysledky
        rf = ttk.LabelFrame(mid, text="Výsledek", style="H.TLabelframe", padding=8)
        rf.pack(side="right", fill="y", padx=(6, 0))
        tf.pack(side="left", fill="both", expand=True)
        self.lbl_round = ttk.Label(rf, text="Kolo: –", style="Big.TLabel")
        self.lbl_round.pack(anchor="w")
        self.lbl_sift = ttk.Label(rf, text="Prosáté bity: –", style="Big.TLabel")
        self.lbl_sift.pack(anchor="w")
        ttk.Label(rf, text="QBER (chybovost testovacích bitů):", style="Big.TLabel").pack(anchor="w", pady=(10, 0))
        self.qber_cv = tk.Canvas(rf, width=300, height=46, bg="white", highlightthickness=0)
        self.qber_cv.pack()
        self.lbl_qber = ttk.Label(rf, text="–", style="Big.TLabel", wraplength=300)
        self.lbl_qber.pack(anchor="w")
        self._draw_qber(None)
        ttk.Label(rf, text="Sdílený tajný klíč (16 bit):", style="Big.TLabel").pack(anchor="w", pady=(14, 0))
        self.lbl_key = ttk.Label(rf, text="– – – –", style="Key.TLabel")
        self.lbl_key.pack(anchor="w")
        self.lbl_keyhex = ttk.Label(rf, text="", style="Big.TLabel")
        self.lbl_keyhex.pack(anchor="w")
        ttk.Label(rf, text="Log Arduin:").pack(anchor="w", pady=(10, 0))
        self.log = tk.Text(rf, width=40, height=10, font=("Consolas", 8))
        self.log.pack(fill="both", expand=True)

        # --- obrazek
        imf = ttk.LabelFrame(self.root, text="Šifrovaný přenos obrázku (XOR každých 16 bitů s klíčem)",
                             style="H.TLabelframe", padding=6)
        imf.pack(fill="x", padx=6, pady=6)
        ctl = ttk.Frame(imf)
        ctl.pack(side="left", fill="y", padx=(0, 10))
        ttk.Button(ctl, text="📂 Nahrát obrázek", command=self.load_image).pack(fill="x")
        ttk.Label(ctl, text="Rozlišení (px):").pack(anchor="w", pady=(8, 0))
        self.size = ttk.Combobox(ctl, values=[8, 16, 24, 32, 48, 64], width=6, state="readonly")
        self.size.set(32)
        self.size.pack(anchor="w")
        ttk.Label(ctl, text="Barevná hloubka:").pack(anchor="w", pady=(8, 0))
        self.mode = ttk.Combobox(ctl, values=[m[0] for m in qcrypt.MODES.values()], width=22, state="readonly")
        self.mode.current(2)
        self.mode.pack(anchor="w")
        for w in (self.size, self.mode):
            w.bind("<<ComboboxSelected>>", lambda e: self.update_preview())
        self.lbl_size = ttk.Label(ctl, text="", wraplength=200)
        self.lbl_size.pack(anchor="w", pady=6)
        self.btn_send = ttk.Button(ctl, text="🔒 Zašifrovat a poslat Bobovi", command=self.send_image,
                                   state="disabled")
        self.btn_send.pack(fill="x")
        self.progress = ttk.Progressbar(ctl, length=200)
        self.progress.pack(pady=6)

        self.canvases = {}
        for name, title in (("orig", "ALICE: originál\n(po kompresi)"),
                            ("aenc", "ALICE: zašifrováno\n(odesláno linkou)"),
                            ("benc", "BOB: přijatá data\n(bez klíče jen šum)"),
                            ("bdec", "BOB: dešifrováno\nsvým klíčem")):
            f = ttk.Frame(imf)
            f.pack(side="left", padx=6)
            ttk.Label(f, text=title, justify="center").pack()
            lbl = ttk.Label(f)
            lbl.pack()
            self.canvases[name] = lbl
            self._show(name, np.full((8, 8, 3), 230, np.uint8))
            if name in ("orig", "benc"):
                ttk.Label(imf, text="→", font=("Segoe UI", 22)).pack(side="left")

    def _ports(self):
        try:
            from serial.tools import list_ports
            return [p.device for p in list_ports.comports()]
        except Exception:
            return []

    # ------------------------------------------------------------ helpers
    def say(self, text):
        self.explain.config(text=text)

    def _show(self, name, arr):
        img = Image.fromarray(arr).resize((PREVIEW, PREVIEW), Image.NEAREST)
        ph = ImageTk.PhotoImage(img)
        self.canvases[name].configure(image=ph)
        self.canvases[name].image = ph

    def _draw_qber(self, q):
        cv = self.qber_cv
        cv.delete("all")
        W, top = 300, 6
        scale = W / 0.5                      # osa 0 - 50 %
        cv.create_rectangle(0, top, QBER_LIMIT * scale, 26, fill="#c8f7c5", outline="")
        cv.create_rectangle(QBER_LIMIT * scale, top, W, 26, fill="#ffd6d6", outline="")
        for v, t in ((0, "0"), (QBER_LIMIT, "11 %"), (0.25, "25 % (Eve)"), (0.5, "50 %")):
            x = min(v * scale, W - 1)
            cv.create_line(x, top, x, 30, fill="#555")
            cv.create_text(min(max(x, 12), W - 30), 38, text=t, font=("Segoe UI", 8))
        if q is not None:
            x = min(q * scale, W - 2)
            cv.create_polygon(x - 6, 0, x + 6, 0, x, 14, fill="black")

    def logline(self, who, line):
        self.log.insert("end", f"{who[0].upper()}> {line}\n")
        self.log.see("end")

    # ------------------------------------------------------------ connect / QKD
    def connect(self):
        try:
            if self.sim.get():
                self.backend = SimBackend(self.events, self.eve.get)
                self.root.after(100, lambda: self.btn_start.config(state="normal"))
            else:
                self.backend = SerialBackend(self.alice_port.get(), self.bob_port.get(), self.events)
                self.root.after(2500, lambda: (self.btn_start.config(state="normal"),
                                               self.status.config(text="Připojeno – Arduina připravena")))
            self.btn_conn.config(state="disabled")
        except Exception as e:
            self.status.config(text=f"Chyba: {e}")

    def start(self):
        self.btn_start.config(state="disabled")
        self.key = None
        self.backend.start_qkd()
        self.say("Startuji... Alice a Bob si po klasické lince (SoftwareSerial) jen domlouvají "
                 "načasování. Samotné bity letí laserem – kvantovým kanálem.")

    def _poll(self):
        try:
            while True:
                self.handle(*self.events.get_nowait())
        except queue.Empty:
            pass
        self.root.after(50, self._poll)

    def handle(self, src, data):
        if src == "status":
            self.status.config(text=data)
            return
        if src == "bobraw":
            self.receive_bytes(data)
            return
        if src == "progress":
            self.progress["value"] = data
            return
        if src == "sent":
            self.on_sent(data)
            return
        if not data.startswith("#"):
            self.logline(src, data)
        ev = parse_line(data)
        if not ev:
            return
        kind, val = ev
        if kind == "ROUND":
            self.new_round(val)
        elif kind == "A":
            self.on_alice(*val)
        elif kind == "B":
            self.on_bob(*val)
        elif kind == "RESULT" and src == "alice":
            self.on_result(val)
        elif kind == "KEY":
            self.on_key(src, val)

    def new_round(self, n):
        self.round = Round(n)
        self.tree.delete(*self.tree.get_children())
        self.lbl_round.config(text=f"Kolo: {n}   ({N_QUBITS} qubitů)")
        self.lbl_sift.config(text="Prosáté bity: –")
        self._draw_qber(None)
        self.lbl_qber.config(text="–")

    def on_alice(self, i, base, bit):
        if self.round is None:
            self.new_round(1)
        self.round.alice[i] = (base, bit)
        self.tree.insert("", "end", iid=str(i), tags=("pending",),
                         values=(i, BASIS[base], bit, HWP[(base, bit)], POL[(base, bit)], "…", "…", "", ""))
        self.tree.see(str(i))
        self.say(f"Qubit {i}: Alice náhodně zvolila bit {bit} v bázi {BASIS[base].split()[0]} → "
                 f"natočí HWP na {HWP[(base, bit)]}, laser má polarizaci {POL[(base, bit)]}. "
                 f"Servo odkryje shutter a laser posvítí k Bobovi.")

    def on_bob(self, i, base, res):
        if self.round is None or i not in self.round.alice:
            return
        self.round.bob[i] = (base, res)
        ab, abit = self.round.alice[i]
        match = "ANO" if ab == base else "ne"
        tag = "lost" if res is None else ("pending" if ab == base else "drop")
        self.tree.item(str(i), tags=(tag,), values=(i, BASIS[ab], abit, HWP[(ab, abit)], POL[(ab, abit)],
                                                    BASIS[base], DET[res], match, ""))
        if res is None:
            txt = "nic nezachytil (ztráta) – qubit se zahodí."
        elif ab == base:
            txt = f"měřil ve STEJNÉ bázi → výsledek {res} by měl být stejný jako bit Alice ({abit})."
        else:
            txt = f"měřil v JINÉ bázi → výsledek {res} je náhodný (50/50), qubit se později zahodí."
        self.say(f"Qubit {i}: Bob náhodně zvolil bázi {BASIS[base].split()[0]} a {txt}")

    def on_result(self, res):
        an = self.round.analysis() if self.round else None
        if an:
            self.colour_rows(an)
            n = len(an["sifted"])
            self.lbl_sift.config(text=f"Prosáté bity: {n}/{N_QUBITS} (≈ polovina)\n"
                                      f"  klíč: {len(an['key_idx'])}, test: {len(an['test_idx'])}")
            q = an["qber"]
            self._draw_qber(q)
        if res == "FEW":
            self.say("Málo bitů se shodnou bází – kolo se opakuje.")
            return
        q = an["qber"] if an else 0
        txt = f"QBER = {len(an['errors'])}/{len(an['test_idx'])} = {q * 100:.1f} %"
        if res == "FAIL":
            self.lbl_qber.config(text=txt + "\n⚠ NAD PRAHEM 11 % → někdo odposlouchává (Eve)! "
                                            "Klíč se zahazuje a zkouší se znovu.", foreground="red")
            self.say("Sifting: Alice a Bob si VEŘEJNĚ řekli svoje báze (ne bity!) a ponechali jen qubity "
                     "se shodnou bází. Část z nich veřejně porovnali – chyb je moc. Eve, která měří a "
                     "znovu posílá, se ve 50 % trefí do špatné báze → ~25 % chyb. Klíč NENÍ bezpečný.")
        else:
            self.lbl_qber.config(text=txt + "\n✔ pod prahem 11 % → nikdo neposlouchá.", foreground="green")
            self.say("Sifting: Alice a Bob si VEŘEJNĚ řekli svoje báze (ne bity!) a ponechali jen qubity se "
                     "shodnou bází (zelené + modré). Modré (testovací) bity veřejně porovnali → chybovost je "
                     "nízká, takže nikdo neposlouchal. Prvních 16 zelených bitů je tajný klíč.")

    def colour_rows(self, an):
        keyset, testset, errs = set(an["key_idx"]), set(an["test_idx"]), set(an["errors"])
        for i in self.round.alice:
            if not self.tree.exists(str(i)):
                continue
            vals = list(self.tree.item(str(i), "values"))
            if i in errs:
                tag, role = "err", "test – CHYBA"
            elif i in testset:
                tag, role = "test", "test (zveřejněn)"
            elif i in keyset:
                tag, role = "key", f"KLÍČ bit {an['key_idx'].index(i) + 1}"
            elif i in self.round.bob and self.round.bob[i][1] is None:
                tag, role = "lost", "ztráta → zahodit"
            else:
                tag, role = "drop", "jiná báze → zahodit"
            vals[8] = role
            self.tree.item(str(i), tags=(tag,), values=vals)

    def on_key(self, src, key):
        if src == "bob":
            self.bob_key = key
            return
        self.key = key
        b = f"{key:016b}"
        self.lbl_key.config(text=" ".join(b[i:i + 4] for i in range(0, 16, 4)))
        self.lbl_keyhex.config(text=f"hex 0x{key:04X}")
        self.btn_send.config(state="normal" if self.image is not None else "disabled")
        self.say("✔ Klíč je hotový a obě Arduina ho mají. 2) Nahraj obrázek, zvol rozlišení a barevnou "
                 "hloubku (menší = rychlejší přenos po pomalé lince) a stiskni Zašifrovat a poslat.")

    # ------------------------------------------------------------ obrazek
    def load_image(self):
        path = filedialog.askopenfilename(filetypes=[("Obrázky", "*.png *.jpg *.jpeg *.bmp *.gif")])
        if not path:
            return
        self.image = Image.open(path)
        self.update_preview()
        if self.key is not None:
            self.btn_send.config(state="normal")

    def _params(self):
        return int(self.size.get()), self.mode.current()

    def update_preview(self):
        size, mode = self._params()
        n = qcrypt.payload_len(size, size, mode)
        secs = (n + 7) * 10 / 9600 * 1.3
        self.lbl_size.config(text=f"{size}×{size} px, {qcrypt.MODES[mode][1]} bit/px\n"
                                  f"= {n} B, přenos ≈ {secs:.0f} s (9600 Bd)")
        if self.image is None:
            return
        data, prev = qcrypt.encode_image(self.image, size, mode)
        self._show("orig", prev)
        if self.key is not None:
            self._show("aenc", qcrypt.decode_image(qcrypt.xor16(data, self.key), size, size, mode))

    def send_image(self):
        if self.sending or self.image is None or self.key is None:
            return
        size, mode = self._params()
        data, prev = qcrypt.encode_image(self.image, size, mode)
        enc = qcrypt.xor16(data, self.key)
        self._show("orig", prev)
        self.send = dict(size=size, mode=mode, enc=enc)
        self.parser.reset()
        blank = qcrypt.decode_image(b"", size, size, mode)
        for n in ("aenc", "benc", "bdec"):
            self._show(n, blank)
        self.sending = True
        self.btn_send.config(state="disabled")
        self.say(f"Alice rozdělí obrázek na 16bitová slova a každé XORuje klíčem {self.key:016b}. "
                 "Výsledek vypadá jako šum – i když ho Eve odposlechne, bez klíče nic nezjistí. "
                 "Data jdou po klasické lince Alice → Bob.")
        frame = qcrypt.make_frame(enc, size, size, mode)
        threading.Thread(target=self._sender, args=(frame,), daemon=True).start()

    def _sender(self, frame):
        ok = True
        for i in range(0, len(frame), 32):
            if not self.backend.send_chunk(frame[i:i + 32]):
                ok = False
                break
            self.events.put(("progress", 100 * min(i + 32, len(frame)) / len(frame)))
            self.events.put(("sent", min(i + 32, len(frame))))
        if not ok:
            self.events.put(("status", "Alice nepotvrdila data – zkontroluj linku"))

    def on_sent(self, nbytes):
        s = self.send
        k = max(0, min(nbytes - 6, len(s["enc"])))
        self._show("aenc", qcrypt.decode_image(s["enc"][:k], s["size"], s["size"], s["mode"]))

    def receive_bytes(self, chunk):
        p = self.parser
        p.feed(chunk)
        if not p.header:
            return
        w, h, mode = p.header
        key = getattr(self, "bob_key", self.key)
        self._show("benc", qcrypt.decode_image(p.data, w, h, mode))
        self._show("bdec", qcrypt.decode_image(qcrypt.xor16(p.data, key), w, h, mode))
        if p.checksum_ok is not None:
            self.sending = False
            self.btn_send.config(state="normal")
            if p.checksum_ok:
                self.say("✔ Bob přijal celý obrázek a XORoval ho STEJNÝM klíčem → dostal originál. "
                         "(XOR dvakrát se stejným klíčem = původní data.) Můžeš zkusit jiné rozlišení.")
            else:
                self.say("⚠ Obrázek dorazil, ale kontrolní součet nesedí – část dat se po lince poškodila.")


if __name__ == "__main__":
    root = tk.Tk()
    root.geometry("1250x900")
    App(root)
    root.mainloop()
