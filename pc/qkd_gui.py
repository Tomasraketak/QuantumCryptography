"""QKD demonstrátor BB84 - jedno okno pro Alici i Boba.

Spuštění:  python qkd_gui.py
Obě Arduina připoj USB do jednoho PC, vyber porty a dej Připojit.
Bez hardwaru zaškrtni "Simulace" (a případně "Eve poslouchá").

Alice a Bob jsou v kódu oddělení (qkd_core.Alice / qkd_core.Bob). GUI je jen
"pozorovatel", který ukazuje, co každý z nich dělá - Bob z GUI nic nedostává.
"""
import queue
import tkinter as tk
from tkinter import filedialog, ttk

import numpy as np
from PIL import Image, ImageTk

import qcrypt
from qkd_core import (KEY_BITS, N_QUBITS, QBER_LIMIT, SerialDevice, Session, SimOptics)

BASIS = ["HV (+)", "DA (×)"]
POL = {(0, 0): "↔ H", (0, 1): "↕ V", (1, 0): "⤢ D", (1, 1): "⤡ A"}
HWP = {(0, 0): "45°", (0, 1): "0°", (1, 0): "-22.5°", (1, 1): "+22.5°"}
BOB_HWP = ["0°", "+22.5°"]
DET = {0: "detektor 0 → 0", 1: "detektor 1 → 1", None: "nic (ztráta)"}
PREVIEW = 190

INTRO = ("1) Připoj obě Arduina (nebo zapni simulaci) a stiskni START.\n"
         "PC za Alici náhodně volí bit a bázi a natáčí její HWP, za Boba náhodně volí bázi. "
         "Bob se bit dozví JEN z toho, na kterém detektoru se objeví laser.")


class App:
    def __init__(self, root):
        self.root = root
        root.title("Kvantová distribuce klíče BB84 – Alice & Bob")
        self.events = queue.Queue()
        self.session = None
        self.devices = {}
        self.rows = {}          # i -> {"a": (baze, bit), "b": (baze, vysledek)}
        self.keys = {}
        self.image = None
        self.alice_img = None
        self._build()
        self.root.after(50, self._poll)

    # ------------------------------------------------------------ layout
    def _build(self):
        st = ttk.Style()
        st.configure("Big.TLabel", font=("Segoe UI", 11))
        st.configure("Key.TLabel", font=("Consolas", 14, "bold"))
        st.configure("H.TLabelframe.Label", font=("Segoe UI", 11, "bold"))

        top = ttk.Frame(self.root, padding=6)
        top.pack(fill="x")
        ports = self._ports()
        ttk.Label(top, text="Alice port:").pack(side="left")
        self.alice_port = ttk.Combobox(top, values=ports, width=10)
        self.alice_port.pack(side="left", padx=3)
        ttk.Label(top, text="Bob port:").pack(side="left")
        self.bob_port = ttk.Combobox(top, values=ports, width=10)
        self.bob_port.pack(side="left", padx=3)
        if len(ports) >= 2:
            self.alice_port.set(ports[0]); self.bob_port.set(ports[1])
        self.sim = tk.BooleanVar(value=not ports)
        ttk.Checkbutton(top, text="Simulace (bez HW)", variable=self.sim).pack(side="left", padx=6)
        self.eve = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text="Eve poslouchá (simulace)", variable=self.eve).pack(side="left")
        self.btn_conn = ttk.Button(top, text="Připojit", command=self.connect)
        self.btn_conn.pack(side="left", padx=6)
        self.btn_start = ttk.Button(top, text="▶ START – vytvořit klíč", command=self.start, state="disabled")
        self.btn_start.pack(side="left")
        self.status = ttk.Label(top, text="Nepřipojeno")
        self.status.pack(side="left", padx=8)

        # ruční ovládání / kalibrace
        man = ttk.Frame(self.root, padding=(6, 0))
        man.pack(fill="x")
        for who, cmds in (("alice", "V H D A O C ZERO"), ("bob", "V H D A M ZERO d")):
            ttk.Label(man, text=f"Ručně {who.capitalize()}:").pack(side="left", padx=(8, 2))
            for c in cmds.split():
                ttk.Button(man, text=c, width=6, command=lambda w=who, c=c: self.manual(w, c)).pack(side="left")
            e = ttk.Entry(man, width=8)
            e.pack(side="left", padx=2)
            e.bind("<Return>", lambda ev, w=who, e=e: self.manual(w, e.get()))
        ttk.Label(man, text="(pole: např. 'k15' = pootoč o 15°, 'k-2.5' + Enter)").pack(side="left", padx=6)

        self.explain = tk.Label(self.root, text=INTRO, font=("Segoe UI", 11), wraplength=1250,
                                justify="left", padx=8, pady=6, bg="#fff8dc", relief="groove")
        self.explain.pack(fill="x", padx=6, pady=4)

        mid = ttk.Frame(self.root, padding=6)
        mid.pack(fill="both", expand=True)

        # --- pravý panel: výsledek + veřejný kanál
        rf = ttk.LabelFrame(mid, text="Výsledek", style="H.TLabelframe", padding=6)
        rf.pack(side="right", fill="y", padx=(6, 0))
        self.lbl_round = ttk.Label(rf, text="Kolo: –", style="Big.TLabel")
        self.lbl_round.pack(anchor="w")
        self.lbl_sift = ttk.Label(rf, text="Prosáté bity: –", style="Big.TLabel")
        self.lbl_sift.pack(anchor="w")
        ttk.Label(rf, text="QBER (chybovost testovacích bitů):", style="Big.TLabel").pack(anchor="w", pady=(6, 0))
        self.qber_cv = tk.Canvas(rf, width=300, height=46, bg="white", highlightthickness=0)
        self.qber_cv.pack()
        self.lbl_qber = ttk.Label(rf, text="–", wraplength=300)
        self.lbl_qber.pack(anchor="w")
        self._draw_qber(None)
        ttk.Label(rf, text="Klíč Alice (zná jen Alice):").pack(anchor="w", pady=(8, 0))
        self.lbl_akey = ttk.Label(rf, text="– – – –", style="Key.TLabel")
        self.lbl_akey.pack(anchor="w")
        ttk.Label(rf, text="Klíč Boba (z jeho měření):").pack(anchor="w")
        self.lbl_bkey = ttk.Label(rf, text="– – – –", style="Key.TLabel")
        self.lbl_bkey.pack(anchor="w")
        self.lbl_match = ttk.Label(rf, text="", style="Big.TLabel")
        self.lbl_match.pack(anchor="w")
        ttk.Label(rf, text="Veřejný kanál (vidí i Eve):").pack(anchor="w", pady=(8, 0))
        self.pub = tk.Text(rf, width=44, height=12, font=("Consolas", 8), wrap="word")
        self.pub.pack(fill="both", expand=True)

        # --- tabulka qubitů
        tf = ttk.LabelFrame(mid, text="Kvantový kanál – qubit po qubitu", style="H.TLabelframe")
        tf.pack(side="left", fill="both", expand=True)
        ttk.Label(tf, text="zelená = bit klíče   modrá = testovací bit (zveřejněn)   "
                           "červená = chyba   šedá = jiná báze / ztráta → zahozeno").pack(side="bottom", anchor="w")
        cols = ("i", "abase", "abit", "hwp", "pol", "bbase", "bhwp", "bdet", "match", "role")
        heads = ("#", "Alice báze", "Alice bit", "Alice HWP", "polarizace", "Bob báze", "Bob HWP",
                 "Bob naměřil", "báze stejné?", "použití")
        widths = (32, 70, 60, 70, 70, 70, 65, 110, 85, 130)
        self.tree = ttk.Treeview(tf, columns=cols, show="headings", height=16)
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

        # --- obrázek
        imf = ttk.LabelFrame(self.root, text="Šifrovaný přenos obrázku (XOR každých 16 bitů s klíčem)",
                             style="H.TLabelframe", padding=6)
        imf.pack(fill="x", padx=6, pady=6)
        ctl = ttk.Frame(imf)
        ctl.pack(side="left", fill="y", padx=(0, 10))
        ttk.Button(ctl, text="📂 Nahrát obrázek", command=self.load_image).pack(fill="x")
        ttk.Label(ctl, text="Rozlišení (px):").pack(anchor="w", pady=(6, 0))
        self.size = ttk.Combobox(ctl, values=[8, 16, 24, 32, 48, 64], width=6, state="readonly")
        self.size.set(32)
        self.size.pack(anchor="w")
        ttk.Label(ctl, text="Barevná hloubka:").pack(anchor="w", pady=(6, 0))
        self.mode = ttk.Combobox(ctl, values=[m[0] for m in qcrypt.MODES.values()], width=22, state="readonly")
        self.mode.current(2)
        self.mode.pack(anchor="w")
        for w in (self.size, self.mode):
            w.bind("<<ComboboxSelected>>", lambda e: self.update_preview())
        self.lbl_size = ttk.Label(ctl, text="", wraplength=200)
        self.lbl_size.pack(anchor="w", pady=4)
        self.btn_send = ttk.Button(ctl, text="🔒 Alice zašifruje a pošle", command=self.send_image, state="disabled")
        self.btn_send.pack(fill="x")
        self.progress = ttk.Progressbar(ctl, length=200)
        self.progress.pack(pady=6)

        self.views = {}
        for name, title in (("orig", "ALICE: originál\n(jen u Alice)"),
                            ("aenc", "ALICE: zašifrováno\nklíčem Alice"),
                            ("benc", "BOB: přijal z veřejného\nkanálu (šum)"),
                            ("bdec", "BOB: dešifroval\nSVÝM klíčem")):
            f = ttk.Frame(imf)
            f.pack(side="left", padx=5)
            ttk.Label(f, text=title, justify="center").pack()
            lbl = ttk.Label(f)
            lbl.pack()
            self.views[name] = lbl
            self._show(name, np.full((8, 8, 3), 230, np.uint8))
            if name in ("orig", "aenc"):
                ttk.Label(imf, text="→", font=("Segoe UI", 20)).pack(side="left")

    def _ports(self):
        try:
            from serial.tools import list_ports
            return [p.device for p in list_ports.comports()]
        except Exception:
            return []

    # ------------------------------------------------------------ pomocné
    def say(self, text):
        self.explain.config(text=text)

    def _show(self, name, arr):
        img = Image.fromarray(arr).resize((PREVIEW, PREVIEW), Image.NEAREST)
        ph = ImageTk.PhotoImage(img)
        self.views[name].configure(image=ph)
        self.views[name].image = ph

    def _draw_qber(self, q):
        cv, W, scale = self.qber_cv, 300, 300 / 0.5
        cv.delete("all")
        cv.create_rectangle(0, 6, QBER_LIMIT * scale, 26, fill="#c8f7c5", outline="")
        cv.create_rectangle(QBER_LIMIT * scale, 6, W, 26, fill="#ffd6d6", outline="")
        for v, t in ((0, "0"), (QBER_LIMIT, "11 %"), (0.25, "25 % (Eve)"), (0.5, "50 %")):
            x = min(v * scale, W - 1)
            cv.create_line(x, 6, x, 30, fill="#555")
            cv.create_text(min(max(x, 12), W - 30), 38, text=t, font=("Segoe UI", 8))
        if q is not None:
            x = min(q * scale, W - 2)
            cv.create_polygon(x - 6, 0, x + 6, 0, x, 14, fill="black")

    def publog(self, text):
        self.pub.insert("end", text + "\n")
        self.pub.see("end")

    @staticmethod
    def _keytxt(k):
        b = f"{k:016b}"
        return " ".join(b[i:i + 4] for i in range(0, 16, 4)) + f"  (0x{k:04X})"

    # ------------------------------------------------------------ připojení
    def connect(self):
        try:
            if self.sim.get():
                optics = SimOptics(eve=self.eve.get)
                self.devices = {"alice": optics.device("alice"), "bob": optics.device("bob")}
                self.status.config(text="Simulace připravena (bez hardwaru)")
            else:
                log = lambda who, t: self.events.put(("HWLOG", who, t))
                self.devices = {"alice": SerialDevice(self.alice_port.get(), "Alice", log),
                                "bob": SerialDevice(self.bob_port.get(), "Bob", log)}
                self.status.config(text="Arduina připojena")
            self.btn_conn.config(state="disabled")
            self.btn_start.config(state="normal")
        except Exception as e:
            self.status.config(text=f"Chyba: {e}")

    def manual(self, who, c):
        if who not in self.devices or (self.session and not self.keys):
            return
        try:
            r = self.devices[who].cmd(c.strip())
            self.status.config(text=f"{who}: {c} → {r}")
        except Exception as e:
            self.status.config(text=f"Chyba: {e}")

    def start(self):
        self.btn_start.config(state="disabled")
        self.session = Session(self.events, self.devices["alice"], self.devices["bob"])
        self.session.start()

    # ------------------------------------------------------------ události
    def _poll(self):
        try:
            for _ in range(200):
                self.handle(*self.events.get_nowait())
        except queue.Empty:
            pass
        self.root.after(40, self._poll)

    def handle(self, kind, *a):
        getattr(self, "on_" + kind, lambda *x: None)(*a)

    def on_ERROR(self, text):
        self.status.config(text=text)
        self.say("⚠ " + text)

    def on_HWLOG(self, who, text):
        pass

    def on_PUB(self, frm, kind, shown):
        if kind in ("IMG_DATA",):
            return
        arrow = "A → B" if frm == "alice" else "B → A"
        txt = "" if shown is None else f" {shown}"
        if kind in ("READY", "BOB_READY", "OPEN", "MEASURED", "CLOSED", "DARK"):
            return          # synchronizace qubitů - jen čas, nic tajného; nezahlcovat log
        self.publog(f"{arrow} {kind}:{txt}")

    def on_ROUND(self, n):
        self.rows = {}
        self.tree.delete(*self.tree.get_children())
        self.lbl_round.config(text=f"Kolo: {n}   ({N_QUBITS} qubitů)")
        self.lbl_sift.config(text="Prosáté bity: –")
        self._draw_qber(None)
        self.lbl_qber.config(text="–", foreground="black")
        self.publog(f"===== kolo {n} =====")

    def on_A(self, i, base, bit):
        self.rows[i] = {"a": (base, bit)}
        self.tree.insert("", "end", iid=str(i), tags=("pending",),
                         values=(i, BASIS[base], bit, HWP[(base, bit)], POL[(base, bit)], "…", "…", "…", "", ""))
        self.tree.see(str(i))
        self.say(f"Qubit {i}: Alice náhodně zvolila bit {bit} v bázi {BASIS[base]} → HWP na {HWP[(base, bit)]}, "
                 f"laser má polarizaci {POL[(base, bit)]}. Bob mezitím náhodně volí svou bázi, "
                 f"pak se otevře shutter a Bob čeká, až detektor ohlásí VALID.")

    def on_B(self, i, base, res):
        if i not in self.rows:
            return
        self.rows[i]["b"] = (base, res)
        ab, abit = self.rows[i]["a"]
        tag = "lost" if res is None else ("pending" if ab == base else "drop")
        self.tree.item(str(i), tags=(tag,), values=(i, BASIS[ab], abit, HWP[(ab, abit)], POL[(ab, abit)],
                                                    BASIS[base], BOB_HWP[base], DET[res],
                                                    "ANO" if ab == base else "ne", ""))
        if res is None:
            txt = "nic nezachytil (ztráta) – qubit se zahodí."
        elif ab == base:
            txt = f"měřil ve STEJNÉ bázi → naměřil {res}, měl by mít stejný bit jako Alice."
        else:
            txt = f"měřil v JINÉ bázi → výsledek {res} je náhodný (50/50), později se zahodí."
        self.say(f"Qubit {i}: Bob (báze {BASIS[base]}) {txt} Shutter se zavře a čeká se, "
                 f"až detektor zhasne (+100 ms).")

    def on_RESULT(self, verdict, qber):
        sifted = [i for i in sorted(self.rows) if "b" in self.rows[i] and self.rows[i]["b"][1] is not None
                  and self.rows[i]["a"][0] == self.rows[i]["b"][0]]
        key_idx, test_idx = sifted[:KEY_BITS], sifted[KEY_BITS:]
        for i in self.rows:
            vals = list(self.tree.item(str(i), "values"))
            a, b = self.rows[i]["a"], self.rows[i].get("b", (None, None))
            if i in test_idx and a[1] != b[1]:
                tag, role = "err", "test – CHYBA"
            elif i in test_idx:
                tag, role = "test", "test (zveřejněn)"
            elif i in key_idx:
                tag, role = "key", f"KLÍČ bit {key_idx.index(i) + 1}" + (" ✘" if a[1] != b[1] else "")
            elif b[1] is None:
                tag, role = "lost", "ztráta → zahodit"
            else:
                tag, role = "drop", "jiná báze → zahodit"
            vals[9] = role
            self.tree.item(str(i), tags=(tag,), values=vals)
        self.lbl_sift.config(text=f"Prosáté bity: {len(sifted)}/{N_QUBITS}\n"
                                  f"  klíč: {len(key_idx)}, test: {len(test_idx)}")
        if verdict == "FEW":
            self.say("Málo qubitů se shodnou bází – kolo se opakuje.")
            return
        self._draw_qber(qber)
        txt = f"QBER = {qber * 100:.1f} %"
        if verdict == "FAIL":
            self.lbl_qber.config(text=txt + "\n⚠ NAD PRAHEM 11 % → pravděpodobně odposlech (Eve)! "
                                            "Klíč se zahazuje, zkouší se znovu.", foreground="red")
            self.say("Sifting: Alice a Bob si VEŘEJNĚ řekli báze (ne bity!) a nechali jen qubity se shodnou "
                     "bází. Část z nich veřejně porovnali – chyb je moc. Eve, která měří a posílá znovu, se ve "
                     "50 % trefí do špatné báze → ~25 % chyb. Klíč NENÍ bezpečný.")
        else:
            self.lbl_qber.config(text=txt + "\n✔ pod prahem 11 % → nikdo neposlouchá.", foreground="green")
            self.say("Sifting: Alice a Bob si VEŘEJNĚ řekli báze (ne bity!) a nechali jen qubity se shodnou bází. "
                     "Modré testovací bity veřejně porovnali → chyb je málo. Prvních 16 zelených bitů je klíč – "
                     "každý si ho složí SÁM ze svých dat.")

    def on_KEY(self, who, key):
        self.keys[who] = key
        (self.lbl_akey if who == "alice" else self.lbl_bkey).config(text=self._keytxt(key))
        if len(self.keys) == 2:
            same = self.keys["alice"] == self.keys["bob"]
            self.lbl_match.config(text="✔ klíče jsou stejné" if same else "✘ klíče se LIŠÍ!",
                                  foreground="green" if same else "red")
            self.btn_send.config(state="normal" if self.image is not None else "disabled")
            self.say("✔ Klíč je hotový. Alice ani Bob si ho NIKDY neposlali – každý ho má ze svých bitů. "
                     "2) Nahraj obrázek, zvol rozlišení a barevnou hloubku a nech Alici zašifrovat a poslat.")
            self.update_preview()

    def on_BOB_QBER(self, q):
        pass

    # ------------------------------------------------------------ obrázek
    def load_image(self):
        path = filedialog.askopenfilename(filetypes=[("Obrázky", "*.png *.jpg *.jpeg *.bmp *.gif")])
        if path:
            self.set_image(Image.open(path))

    def set_image(self, img):
        self.image = img
        self.update_preview()
        if len(self.keys) == 2:
            self.btn_send.config(state="normal")

    def _params(self):
        return int(self.size.get()), self.mode.current()

    def update_preview(self):
        size, mode = self._params()
        n = qcrypt.payload_len(size, size, mode)
        self.lbl_size.config(text=f"{size}×{size} px, {qcrypt.MODES[mode][1]} bit/px = {n} B")
        if self.image is not None:
            self._show("orig", qcrypt.encode_image(self.image, size, mode)[1])

    def send_image(self):
        if self.image is None or len(self.keys) < 2:
            return
        self.btn_send.config(state="disabled")
        size, mode = self._params()
        blank = qcrypt.decode_image(b"", size, size, mode)
        for v in ("aenc", "benc", "bdec"):
            self._show(v, blank)
        self.session.send_image(self.image, size, mode)
        self.say("Alice rozdělí obrázek na 16bitová slova a každé XORuje SVÝM klíčem. Veřejným kanálem jde jen "
                 "šifrovaný šum – Eve bez klíče nic nezjistí. Bob dešifruje SVÝM klíčem: když kvantový kanál "
                 "fungoval, klíče jsou stejné a obrázek se objeví.")

    def on_ALICE_IMG(self, preview, enc, size, mode):
        self.alice_img = (enc, size, mode)
        self._show("orig", preview)

    def on_ALICE_SENT(self, n):
        enc, size, mode = self.alice_img
        self.progress["value"] = 100 * n / len(enc)
        self._show("aenc", qcrypt.decode_image(enc[:n], size, size, mode))

    def on_BOB_IMG(self, enc, dec, size, mode):
        self._show("benc", qcrypt.decode_image(enc, size, size, mode))
        self._show("bdec", qcrypt.decode_image(dec, size, size, mode))

    def on_BOB_IMG_DONE(self):
        self.btn_send.config(state="normal")
        if self.keys.get("alice") == self.keys.get("bob"):
            self.say("✔ Bob přijal celý obrázek a XORoval ho svým klíčem → dostal originál. "
                     "(XOR dvakrát stejným klíčem = původní data.) Zkus jiné rozlišení nebo barevnou hloubku.")
        else:
            self.say("✘ Bobův klíč se liší od Alicina → obrázek zůstal nečitelný. Kvantový kanál nefungoval správně.")


if __name__ == "__main__":
    root = tk.Tk()
    root.geometry("1320x940")
    App(root)
    root.mainloop()
