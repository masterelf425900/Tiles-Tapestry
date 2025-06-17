import os
import base64
import json
import tkinter as tk
import tkinter.ttk as ttk
from tkinter import filedialog, messagebox, simpledialog
from io import BytesIO
from PIL import Image, ImageTk, ImageDraw

# ----------------------------------------------------------------
# Global Style / Color Configuration
# ----------------------------------------------------------------
PRIMARY_COLOR   = "#abbfe2"   # Main background color 
SECONDARY_COLOR = "#8493af"   # Secondary color
ACCENT_COLOR    = "#dc5697"   # Accent color
TEXT_COLOR      = "#000000"   # Text color for dark backgrounds

WINDOW_ALPHA = 0.95  # overall window alpha

def hex_to_rgb(hex_color):
    c = hex_color.strip()
    if c.startswith("#"):
        c = c[1:]
    if len(c) == 6:
        r = int(c[0:2], 16)
        g = int(c[2:4], 16)
        b = int(c[4:6], 16)
        return (r, g, b)
    return (0, 0, 0)

def rgb_to_hex(rgb):
    return "#{:02x}{:02x}{:02x}".format(*rgb)

def lighten_color(hex_color, factor=0.2):
    r, g, b = hex_to_rgb(hex_color)
    r = int(r + (255 - r) * factor)
    g = int(g + (255 - g) * factor)
    b = int(b + (255 - b) * factor)
    return rgb_to_hex((r, g, b))

def darken_color(hex_color, factor=0.2):
    r, g, b = hex_to_rgb(hex_color)
    r = int(r * (1 - factor))
    g = int(g * (1 - factor))
    b = int(b * (1 - factor))
    return rgb_to_hex((r, g, b))

ACCENT_HOVER   = lighten_color(ACCENT_COLOR, 0.2)
ACCENT_PRESSED = darken_color(ACCENT_COLOR, 0.2)

# ----------------------------------------------------------------
# Utility Functions for Image Processing
# ----------------------------------------------------------------
def parse_hex_color(hex_color: str):
    c = hex_color.strip()
    if c.startswith('#'):
        c = c[1:]
    if len(c) == 6:
        try:
            r = int(c[0:2], 16)
            g = int(c[2:4], 16)
            b = int(c[4:6], 16)
            return (r, g, b, 255)
        except ValueError:
            pass
    return (0, 0, 0, 255)

def crop_to_aspect(img, target_w, target_h):
    orig_w, orig_h = img.size
    target_aspect = target_w / target_h
    orig_aspect = orig_w / orig_h
    if target_aspect > orig_aspect:
        new_height = int(orig_w / target_aspect)
        top = (orig_h - new_height) // 2
        return img.crop((0, top, orig_w, top + new_height))
    else:
        new_width = int(orig_h * target_aspect)
        left = (orig_w - new_width) // 2
        return img.crop((left, 0, left + new_width, orig_h))

def create_rounded_mask(width, height, corner_radius):
    mask = Image.new('L', (width, height), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, width, height), radius=corner_radius, fill=255)
    return mask

# ----------------------------------------------------------------
# Tooltip Class for Hover Info in Preview
# ----------------------------------------------------------------
class Tooltip:
    def __init__(self, widget):
        self.widget = widget
        self.tipwindow = None
        self.text = ""
    def showtip(self, text):
        self.text = text
        if self.tipwindow or not self.text:
            return
        x, y, cx, cy = self.widget.bbox("insert")
        x = x + self.widget.winfo_rootx() + 20
        y = y + self.widget.winfo_rooty() + 20
        self.tipwindow = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_attributes("-topmost", True)
        tw.configure(bg=SECONDARY_COLOR)
        label = tk.Label(tw, text=self.text, justify=tk.LEFT,
                         bg=SECONDARY_COLOR, fg=TEXT_COLOR,
                         relief=tk.SOLID, borderwidth=1,
                         font=("Helvetica", 9))
        label.pack(ipadx=4)
        tw.wm_geometry("+%d+%d" % (x, y))
    def hidetip(self):
        if self.tipwindow:
            self.tipwindow.destroy()
        self.tipwindow = None

# ----------------------------------------------------------------
# Data Structure for an Image Entry
# ----------------------------------------------------------------
class ImageEntry:
    def __init__(self, path, orig_w, orig_h, target_w, target_h):
        self.path = path  # For embedded images, this might be a pseudo path.
        self.orig_w = orig_w
        self.orig_h = orig_h
        self.target_w = target_w
        self.target_h = target_h
        self.x = None   # Auto-assigned x in collage
        self.y = None   # Auto-assigned y in collage
        self.manual_x = None  # Optional manual override
        self.manual_y = None
    @property
    def filename(self):
        return os.path.basename(self.path)
    def get_display_pos(self):
        return (self.manual_x if self.manual_x is not None else self.x,
                self.manual_y if self.manual_y is not None else self.y)
    def __repr__(self):
        return (f"ImageEntry({self.filename}, Orig={self.orig_w}x{self.orig_h}, "
                f"Target={self.target_w}x{self.target_h}, Pos={self.get_display_pos()})")

# ----------------------------------------------------------------
# Main Application Class
# ----------------------------------------------------------------
class CollageApp(tk.Tk):
    OVERFLOW_THRESHOLD = 0.5  # if >50% would overflow, move to next row

    def __init__(self):
        super().__init__()
        self.title("Collage Creator")
        self.attributes("-alpha", WINDOW_ALPHA)

        # Set up ttk style for modern look
        self.style = ttk.Style(self)
        self.style.theme_use("clam")
        self.style.configure(".", background=PRIMARY_COLOR)
        self.style.configure("Accent.TButton",
                             background=ACCENT_COLOR,
                             foreground=TEXT_COLOR,
                             font=("Helvetica", 10, "bold"),
                             borderwidth=0,
                             padding=6,
                             relief="flat")
        self.style.map("Accent.TButton",
                       background=[("active", ACCENT_HOVER),
                                   ("pressed", ACCENT_PRESSED)])
        self.style.configure("TLabel", background=PRIMARY_COLOR, foreground=TEXT_COLOR, font=("Helvetica", 10))
        self.style.configure("TEntry",
                             fieldbackground=SECONDARY_COLOR,
                             foreground=TEXT_COLOR,
                             borderwidth=0,
                             relief="flat",
                             padding=4)
        self.style.configure("TFrame", background=PRIMARY_COLOR)

        # Collage settings variables
        self.collage_width_var = tk.StringVar(value="1920")
        self.collage_height_var = tk.StringVar(value="1080")
        self.border_var = tk.StringVar(value="20")
        self.bg_color_var = tk.StringVar(value="#000000")
        self.corner_radius_var = tk.StringVar(value="0")
        self.scale_var = tk.StringVar(value="2")

        self.images = []  # List of ImageEntry (layer order)

        self.build_main_ui()
        self.preview_window = None
        self.preview_items = {}
        self.selected_preview_entry = None
        self.tooltip = None

    # -------------------------------------------
    # Build Main UI
    # -------------------------------------------
    def build_main_ui(self):
        top_frame = ttk.Frame(self, padding=10)
        top_frame.pack(pady=5)

        ttk.Label(top_frame, text="Collage Width:").grid(row=0, column=0, padx=5, sticky="e")
        ttk.Entry(top_frame, textvariable=self.collage_width_var, width=6).grid(row=0, column=1)
        ttk.Label(top_frame, text="Height:").grid(row=0, column=2, padx=5, sticky="e")
        ttk.Entry(top_frame, textvariable=self.collage_height_var, width=6).grid(row=0, column=3)
        ttk.Label(top_frame, text="Border px:").grid(row=0, column=4, padx=5, sticky="e")
        ttk.Entry(top_frame, textvariable=self.border_var, width=4).grid(row=0, column=5)
        ttk.Label(top_frame, text="BG Color (hex):").grid(row=0, column=6, padx=5, sticky="e")
        ttk.Entry(top_frame, textvariable=self.bg_color_var, width=8).grid(row=0, column=7)
        ttk.Label(top_frame, text="Corner Radius:").grid(row=0, column=8, padx=5, sticky="e")
        ttk.Entry(top_frame, textvariable=self.corner_radius_var, width=4).grid(row=0, column=9)
        ttk.Label(top_frame, text="Scale Factor:").grid(row=0, column=10, padx=5, sticky="e")
        ttk.Entry(top_frame, textvariable=self.scale_var, width=4).grid(row=0, column=11)
        ttk.Button(top_frame, text="Scale Collage", style="Accent.TButton", command=self.scale_collage).grid(row=0, column=12, padx=5)
        ttk.Button(top_frame, text="Preview", style="Accent.TButton", command=self.show_preview).grid(row=0, column=13, padx=5)
        ttk.Button(top_frame, text="Save", style="Accent.TButton", command=self.save_collage).grid(row=0, column=14, padx=5)
        ttk.Button(top_frame, text="Export Project", style="Accent.TButton", command=self.export_project).grid(row=0, column=15, padx=5)
        ttk.Button(top_frame, text="Import Project", style="Accent.TButton", command=self.import_project).grid(row=0, column=16, padx=5)

        lower_frame = ttk.Frame(self, padding=10)
        lower_frame.pack(fill=tk.BOTH, expand=True)

        self.img_listbox = tk.Listbox(lower_frame, width=120, height=8,
                                      bg=SECONDARY_COLOR, fg=TEXT_COLOR,
                                      highlightthickness=0, bd=0,
                                      selectbackground=darken_color(SECONDARY_COLOR, 0.3))
        self.img_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        btns_frame = ttk.Frame(lower_frame)
        btns_frame.pack(side=tk.LEFT, padx=5)
        ttk.Button(btns_frame, text="Add Image", style="Accent.TButton", command=self.add_image).pack(fill=tk.X, pady=2)
        ttk.Button(btns_frame, text="Edit Selected", style="Accent.TButton", command=self.edit_selected_image).pack(fill=tk.X, pady=2)
        ttk.Button(btns_frame, text="Remove Selected", style="Accent.TButton", command=self.remove_selected_image).pack(fill=tk.X, pady=2)

    def refresh_listbox(self):
        self.img_listbox.delete(0, tk.END)
        for entry in self.images:
            x, y = entry.get_display_pos()
            info = f"File: {entry.filename} | Orig: {entry.orig_w}x{entry.orig_h} | Target: {entry.target_w}x{entry.target_h} | Pos: ({x}, {y})"
            self.img_listbox.insert(tk.END, info)

    # -------------------------------------------
    # Auto-Layout with Flexible Overflow
    # -------------------------------------------
    def recalc_layout(self):
        try:
            collage_width = int(self.collage_width_var.get())
            border = int(self.border_var.get())
        except ValueError:
            return
        current_x = border
        current_y = border
        current_row_height = 0
        for entry in self.images:
            if entry.manual_x is not None and entry.manual_y is not None:
                continue
            free_space = collage_width - current_x - border
            if free_space <= 0:
                current_y += current_row_height + border
                current_x = border
                current_row_height = 0
                free_space = collage_width - current_x - border
            if entry.target_w > free_space:
                overflow = entry.target_w - free_space
                ratio = overflow / entry.target_w
                if ratio > self.OVERFLOW_THRESHOLD:
                    current_y += current_row_height + border
                    current_x = border
                    current_row_height = 0
            entry.x = current_x
            entry.y = current_y
            current_row_height = max(current_row_height, entry.target_h)
            current_x += entry.target_w + border

    # -------------------------------------------
    # Add / Edit / Remove Images
    # -------------------------------------------
    def add_image(self):
        path = filedialog.askopenfilename(
            title="Select an image",
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.bmp *.gif")]
        )
        if not path:
            return
        try:
            with Image.open(path) as im:
                orig_w, orig_h = im.size
        except Exception as e:
            messagebox.showerror("Error", f"Cannot open image: {e}")
            return
        self.open_image_dialog(path, orig_w, orig_h)

    def edit_selected_image(self):
        sel_idx = self.img_listbox.curselection()
        if not sel_idx:
            messagebox.showinfo("No Selection", "Select an image to edit.")
            return
        entry = self.images[sel_idx[0]]
        self.open_image_dialog(entry.path, entry.orig_w, entry.orig_h, entry)

    def remove_selected_image(self):
        sel_idx = self.img_listbox.curselection()
        if not sel_idx:
            return
        self.images.pop(sel_idx[0])
        self.recalc_layout()
        self.refresh_listbox()

    # -------------------------------------------
    # Image Settings Dialog (Add/Edit)
    # -------------------------------------------
    def open_image_dialog(self, path, orig_w, orig_h, entry=None):
        dialog = tk.Toplevel(self)
        dialog.title("Image Settings")
        dialog.attributes("-alpha", WINDOW_ALPHA)
        dialog.configure(bg=PRIMARY_COLOR)
        ttk.Label(dialog, text=f"File: {os.path.basename(path)}").pack(anchor="w", padx=5, pady=2)
        ttk.Label(dialog, text=f"Original Size: {orig_w} x {orig_h}").pack(anchor="w", padx=5, pady=2)
        pos_info = "Current Positions:\n"
        for img in self.images:
            px, py = img.get_display_pos()
            pos_info += f"  {img.filename} -> ({px}, {py})\n"
        ttk.Label(dialog, text=pos_info, justify=tk.LEFT).pack(anchor="w", padx=5, pady=2)
        frame = ttk.Frame(dialog, padding=5)
        frame.pack()
        ttk.Label(frame, text="Target Width:").grid(row=0, column=0, padx=5, pady=2, sticky="e")
        tw_entry = ttk.Entry(frame, width=6)
        tw_entry.grid(row=0, column=1, padx=5, pady=2)
        tw_entry.insert(0, str(entry.target_w) if entry else "400")
        ttk.Label(frame, text="Target Height:").grid(row=1, column=0, padx=5, pady=2, sticky="e")
        th_entry = ttk.Entry(frame, width=6)
        th_entry.grid(row=1, column=1, padx=5, pady=2)
        th_entry.insert(0, str(entry.target_h) if entry else "300")
        ttk.Label(frame, text="Manual X (optional):").grid(row=2, column=0, padx=5, pady=2, sticky="e")
        mx_entry = ttk.Entry(frame, width=6)
        mx_entry.grid(row=2, column=1, padx=5, pady=2)
        if entry and entry.manual_x is not None:
            mx_entry.insert(0, str(entry.manual_x))
        ttk.Label(frame, text="Manual Y (optional):").grid(row=3, column=0, padx=5, pady=2, sticky="e")
        my_entry = ttk.Entry(frame, width=6)
        my_entry.grid(row=3, column=1, padx=5, pady=2)
        if entry and entry.manual_y is not None:
            my_entry.insert(0, str(entry.manual_y))
        ttk.Label(frame, text="(Leave manual positions blank for auto–layout)").grid(row=4, column=0, columnspan=2, pady=2)
        btn_frame = ttk.Frame(dialog, padding=5)
        btn_frame.pack()
        def on_ok():
            try:
                tw = int(tw_entry.get())
                th = int(th_entry.get())
            except ValueError:
                messagebox.showwarning("Invalid Input", "Enter valid integers for target size.")
                return
            if tw <= 0 or th <= 0:
                messagebox.showwarning("Invalid Size", "Width and height must be > 0.")
                return
            manual_x = None
            manual_y = None
            if mx_entry.get().strip():
                try:
                    manual_x = int(mx_entry.get())
                except ValueError:
                    messagebox.showwarning("Invalid Input", "Manual X must be an integer.")
                    return
            if my_entry.get().strip():
                try:
                    manual_y = int(my_entry.get())
                except ValueError:
                    messagebox.showwarning("Invalid Input", "Manual Y must be an integer.")
                    return
            if entry:
                entry.target_w = tw
                entry.target_h = th
                entry.manual_x = manual_x
                entry.manual_y = manual_y
            else:
                new_entry = ImageEntry(path, orig_w, orig_h, tw, th)
                new_entry.manual_x = manual_x
                new_entry.manual_y = manual_y
                self.images.append(new_entry)
            self.recalc_layout()
            self.refresh_listbox()
            dialog.destroy()
        ttk.Button(btn_frame, text="OK", style="Accent.TButton", command=on_ok).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Cancel", style="Accent.TButton", command=dialog.destroy).pack(side=tk.LEFT, padx=5)

    # -------------------------------------------
    # Scale Collage (Positive scales up; negative scales down)
    # -------------------------------------------
    def scale_collage(self):
        try:
            factor = float(self.scale_var.get())
        except ValueError:
            messagebox.showwarning("Invalid Scale", "Enter a valid number for scale.")
            return
        if factor < 0:
            factor = 1 / abs(factor)
        try:
            w = float(self.collage_width_var.get())
            h = float(self.collage_height_var.get())
        except ValueError:
            messagebox.showwarning("Invalid Size", "Collage width/height must be valid numbers.")
            return
        self.collage_width_var.set(str(int(w * factor)))
        self.collage_height_var.set(str(int(h * factor)))
        self.recalc_layout()
        self.refresh_listbox()
        if self.preview_window and tk.Toplevel.winfo_exists(self.preview_window):
            self.update_preview()

    # -------------------------------------------
    # Build the Collage Image
    # -------------------------------------------
    def build_collage(self):
        try:
            cw = int(self.collage_width_var.get())
            ch = int(self.collage_height_var.get())
            border = int(self.border_var.get())
            corner_radius = int(self.corner_radius_var.get())
        except ValueError:
            messagebox.showwarning("Invalid Settings", "Width, Height, Border, and Corner Radius must be integers.")
            return None
        bg_rgba = parse_hex_color(self.bg_color_var.get())
        collage = Image.new("RGBA", (cw, ch), bg_rgba)
        safe_area = (border, border, cw - border, ch - border)
        self.recalc_layout()
        for entry in self.images:
            try:
                # If the image is embedded, try to open from memory
                if entry.path.startswith("<embedded:") and hasattr(entry, "_embedded_data"):
                    im = Image.open(BytesIO(entry._embedded_data))
                else:
                    im = Image.open(entry.path)
                cropped = crop_to_aspect(im, entry.target_w, entry.target_h)
                resized = cropped.resize((entry.target_w, entry.target_h), Image.LANCZOS)
                im.close()
            except Exception as e:
                print(f"Error processing {entry.path}: {e}")
                continue
            mask = None
            if corner_radius > 0:
                mask = create_rounded_mask(resized.width, resized.height, corner_radius)
                if resized.mode != "RGBA":
                    resized = resized.convert("RGBA")
            x = entry.manual_x if entry.manual_x is not None else entry.x
            y = entry.manual_y if entry.manual_y is not None else entry.y
            img_box = (x, y, x + entry.target_w, y + entry.target_h)
            inter = (max(img_box[0], safe_area[0]),
                     max(img_box[1], safe_area[1]),
                     min(img_box[2], safe_area[2]),
                     min(img_box[3], safe_area[3]))
            if inter[0] < inter[2] and inter[1] < inter[3]:
                src_x = inter[0] - x
                src_y = inter[1] - y
                src_x2 = src_x + (inter[2] - inter[0])
                src_y2 = src_y + (inter[3] - inter[1])
                portion = resized.crop((src_x, src_y, src_x2, src_y2))
                if mask is not None:
                    portion_mask = mask.crop((src_x, src_y, src_x2, src_y2))
                    collage.paste(portion, inter, portion_mask)
                else:
                    collage.paste(portion, inter)
        return collage

    # -------------------------------------------
    # Preview Window (Interactive)
    # -------------------------------------------
    def show_preview(self):
        if not self.images:
            messagebox.showinfo("No Images", "Add images first.")
            return
        if self.preview_window and tk.Toplevel.winfo_exists(self.preview_window):
            self.preview_window.lift()
            return
        self.preview_window = tk.Toplevel(self)
        self.preview_window.title("Collage Preview")
        self.preview_window.attributes("-alpha", WINDOW_ALPHA)
        self.preview_window.configure(bg=PRIMARY_COLOR)
        top_bar = ttk.Frame(self.preview_window, padding=5)
        top_bar.pack(fill=tk.X)
        ttk.Button(top_bar, text="Refresh", style="Accent.TButton", command=self.update_preview).pack(side=tk.LEFT, padx=5)
        main_frame = ttk.Frame(self.preview_window)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.canvas = tk.Canvas(main_frame, bg=SECONDARY_COLOR, highlightthickness=0)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.details_panel = ttk.Frame(main_frame, padding=10)
        self.details_panel.pack(side=tk.LEFT, fill=tk.Y)
        self.details_label = ttk.Label(self.details_panel, text="Image Details")
        self.details_label.pack(anchor="n")
        self.edit_button = ttk.Button(self.details_panel, text="Edit", style="Accent.TButton",
                                      command=self.edit_selected_from_preview)
        self.edit_button.pack(anchor="n", pady=5)
        self.preview_items = {}
        self.selected_preview_entry = None
        self.tooltip = Tooltip(self.canvas)
        self.update_preview()

    def update_preview(self):
        collage_img = self.build_collage()
        if collage_img is None:
            return
        cw, ch = collage_img.size
        max_w = 800
        if cw > max_w:
            scale = max_w / cw
            preview_img = collage_img.resize((max_w, int(ch * scale)), Image.LANCZOS)
        else:
            scale = 1
            preview_img = collage_img
        self.preview_scale = scale
        self.preview_photo = ImageTk.PhotoImage(preview_img)
        self.canvas.delete("all")
        self.canvas.config(width=preview_img.width, height=preview_img.height)
        self.canvas.create_image(0, 0, anchor="nw", image=self.preview_photo)
        self.preview_items.clear()
        for idx, entry in enumerate(self.images):
            x, y = entry.get_display_pos()
            if x is None or y is None:
                continue
            x_s = x * scale
            y_s = y * scale
            w_s = entry.target_w * scale
            h_s = entry.target_h * scale
            rect = self.canvas.create_rectangle(x_s, y_s, x_s + w_s, y_s + h_s,
                                                outline="", width=2,
                                                tags=("img", f"img_{idx}"))
            self.preview_items[rect] = entry
            self.canvas.tag_bind(rect, "<Enter>", self.on_img_enter)
            self.canvas.tag_bind(rect, "<Leave>", self.on_img_leave)
            self.canvas.tag_bind(rect, "<Button-1>", self.on_img_click)

    def on_img_enter(self, event):
        item = self.canvas.find_withtag("current")
        if item:
            entry = self.preview_items.get(item[0])
            if entry:
                x, y = entry.get_display_pos()
                text = (f"File: {entry.filename}\n"
                        f"Orig: {entry.orig_w}x{entry.orig_h}\n"
                        f"Target: {entry.target_w}x{entry.target_h}\n"
                        f"Pos: ({x}, {y})")
                self.tooltip.showtip(text)

    def on_img_leave(self, event):
        self.tooltip.hidetip()

    def on_img_click(self, event):
        item = self.canvas.find_withtag("current")
        if item:
            entry = self.preview_items.get(item[0])
            if entry:
                self.canvas.delete("highlight")
                x, y = entry.get_display_pos()
                scale = self.preview_scale
                x_s = x * scale
                y_s = y * scale
                w_s = entry.target_w * scale
                h_s = entry.target_h * scale
                self.canvas.create_rectangle(x_s, y_s, x_s + w_s, y_s + h_s,
                                             outline=ACCENT_COLOR, width=3, tags="highlight")
                details = (f"File: {entry.filename}\n"
                           f"Original: {entry.orig_w} x {entry.orig_h}\n"
                           f"Target: {entry.target_w} x {entry.target_h}\n"
                           f"Position: ({x}, {y})")
                self.details_label.config(text=details)
                self.selected_preview_entry = entry

    def edit_selected_from_preview(self):
        if self.selected_preview_entry:
            self.open_image_dialog(self.selected_preview_entry.path,
                                   self.selected_preview_entry.orig_w,
                                   self.selected_preview_entry.orig_h,
                                   self.selected_preview_entry)
            self.update_preview()
            self.refresh_listbox()

    # -------------------------------------------
    # Export Project (Embed all image data)
    # -------------------------------------------
    def export_project(self):
        save_path = filedialog.asksaveasfilename(
            defaultextension=".colproj",
            filetypes=[("Collage Project", "*.colproj"), ("All Files", "*.*")]
        )
        if not save_path:
            return
        try:
            project_data = {
                "collage_settings": {
                    "width": self.collage_width_var.get(),
                    "height": self.collage_height_var.get(),
                    "border": self.border_var.get(),
                    "bg_color": self.bg_color_var.get(),
                    "corner_radius": self.corner_radius_var.get(),
                    "scale": self.scale_var.get(),
                },
                "images": []
            }
            for entry in self.images:
                # If the image was embedded (imported), use the stored _embedded_data.
                if entry.path.startswith("<embedded:") and hasattr(entry, "_embedded_data"):
                    raw_bytes = entry._embedded_data
                else:
                    with open(entry.path, "rb") as f:
                        raw_bytes = f.read()
                b64_data = base64.b64encode(raw_bytes).decode("utf-8")
                img_info = {
                    "orig_w": entry.orig_w,
                    "orig_h": entry.orig_h,
                    "target_w": entry.target_w,
                    "target_h": entry.target_h,
                    "manual_x": entry.manual_x,
                    "manual_y": entry.manual_y,
                    "x": entry.x,
                    "y": entry.y,
                    "filename": entry.filename,
                    "image_data": b64_data
                }
                project_data["images"].append(img_info)
            json_str = json.dumps(project_data, indent=2)
            with open(save_path, "w", encoding="utf-8") as f:
                f.write(json_str)
            messagebox.showinfo("Export Successful", f"Project exported to {save_path}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to export project:\n{e}")

    # -------------------------------------------
    # Import Project (Restore embedded data)
    # -------------------------------------------
    def import_project(self):
        load_path = filedialog.askopenfilename(
            title="Open Collage Project",
            filetypes=[("Collage Project", "*.colproj"), ("All Files", "*.*")]
        )
        if not load_path:
            return
        try:
            with open(load_path, "r", encoding="utf-8") as f:
                json_str = f.read()
            project_data = json.loads(json_str)
            cset = project_data["collage_settings"]
            self.collage_width_var.set(cset["width"])
            self.collage_height_var.set(cset["height"])
            self.border_var.set(cset["border"])
            self.bg_color_var.set(cset["bg_color"])
            self.corner_radius_var.set(cset["corner_radius"])
            self.scale_var.set(cset.get("scale", "2"))
            self.images.clear()
            for img_info in project_data["images"]:
                b64_data = img_info["image_data"]
                raw_bytes = base64.b64decode(b64_data)
                pseudo_path = f"<embedded:{img_info.get('filename','unknown')}>"
                new_entry = ImageEntry(
                    path=pseudo_path,
                    orig_w=img_info["orig_w"],
                    orig_h=img_info["orig_h"],
                    target_w=img_info["target_w"],
                    target_h=img_info["target_h"]
                )
                new_entry.manual_x = img_info["manual_x"]
                new_entry.manual_y = img_info["manual_y"]
                new_entry.x = img_info["x"]
                new_entry.y = img_info["y"]
                new_entry._embedded_data = raw_bytes
                self.images.append(new_entry)
            self.refresh_listbox()
            messagebox.showinfo("Import Successful", f"Project loaded from {load_path}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to import project:\n{e}")

    # -------------------------------------------
    # Save Collage Image to Disk
    # -------------------------------------------
    def save_collage(self):
        if not self.images:
            messagebox.showinfo("No Images", "Add images first.")
            return
        collage_img = self.build_collage()
        if collage_img is None:
            return
        save_path = filedialog.asksaveasfilename(
            defaultextension=".png",
            filetypes=[("PNG file", "*.png"), ("JPEG file", "*.jpg"), ("All Files", "*.*")]
        )
        if save_path:
            try:
                collage_img.save(save_path)
                messagebox.showinfo("Saved", f"Collage saved to {save_path}")
            except Exception as e:
                messagebox.showerror("Error", f"Could not save collage: {e}")

if __name__ == "__main__":
    app = CollageApp()
    app.recalc_layout()
    app.refresh_listbox()
    app.mainloop()
