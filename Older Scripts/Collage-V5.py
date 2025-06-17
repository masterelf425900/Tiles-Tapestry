import os
import base64
import json
import tkinter as tk
import tkinter.ttk as ttk
from tkinter import filedialog, messagebox
from io import BytesIO
from PIL import Image, ImageTk, ImageDraw

# ----------------------------------------------------------------
# Global Style / Color Configuration
# ----------------------------------------------------------------
PRIMARY_COLOR   = "#abbfe2"   # Main background color 
SECONDARY_COLOR = "#8493af"   # Secondary color
ACCENT_COLOR    = "#dc5697"   # Accent color
TEXT_COLOR      = "#000000"   # Text color for dark backgrounds
WINDOW_ALPHA = 1.00  # overall window transparency

def hex_to_rgb(hex_color):
    c = hex_color.strip()
    if c.startswith("#"):
        c = c[1:]
    if len(c) == 6:
        return (int(c[0:2],16), int(c[2:4],16), int(c[4:6],16))
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
            r = int(c[0:2],16)
            g = int(c[2:4],16)
            b = int(c[4:6],16)
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
    mask = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, width, height), radius=corner_radius, fill=255)
    return mask

# ----------------------------------------------------------------
# Tooltip Class for Preview Hover
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
        self.path = path  # For embedded images, may be a pseudo-path.
        self.orig_w = orig_w
        self.orig_h = orig_h
        self.target_w = target_w
        self.target_h = target_h
        self.x = None   # Auto-assigned x
        self.y = None   # Auto-assigned y
        self.manual_x = None  # Manual override of x
        self.manual_y = None  # Manual override of y
        self.locked = False   # When locked, auto-layout will ignore this image.
        self.corner_radius = 0
        self.template_tag = None  
    @property
    def filename(self):
        return os.path.basename(self.path)
    def get_display_pos(self):
        return (self.manual_x if self.manual_x is not None else self.x,
                self.manual_y if self.manual_y is not None else self.y)
    def __repr__(self):
        return (f"ImageEntry({self.filename}, Orig={self.orig_w}x{self.orig_h}, "
                f"Target={self.target_w}x{self.target_h}, Pos={self.get_display_pos()}, Locked={self.locked})")

# ----------------------------------------------------------------
# Main Application Class
# ----------------------------------------------------------------
class CollageApp(tk.Tk):
    OVERFLOW_THRESHOLD = 0.5  # if >50% would overflow, move to next row

    def __init__(self):
        super().__init__()
        self.title("Collage Creator")
        self.attributes("-alpha", WINDOW_ALPHA)

        # Collage settings variables
        self.collage_width_var = tk.StringVar(value="1920")
        self.collage_height_var = tk.StringVar(value="1080")
        self.border_var = tk.StringVar(value="10")
        self.bg_color_var = tk.StringVar(value="#000000")
        self.corner_radius_var = tk.StringVar(value="0")
        self.scale_var = tk.StringVar(value="1")

        self.images = []  # List of ImageEntry objects

        self.templates = {}  # Dictionary to store templates {name: {"width": int, "height": int}}
        self.load_templates()  # Load templates from file
    
        self.build_main_ui()
        self.preview_window = None
        self.preview_items = {}
        self.selected_preview_entry = None
        self.tooltip = None
        self.preview_zoom_factor = 1.0  # Zoom factor for preview

        self.cached_collage = None  # Cache the full-resolution collage
        self.cached_collage_settings = None  # Track when to regenerate cache
        self.canvas_scale_factor = 1.0  # Current canvas zoom level
        self.pan_start_x = 0
        self.pan_start_y = 0
        self.canvas_offset_x = 0
        self.canvas_offset_y = 0

        # Set up ttk style for a modern look
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

    def update_images_with_template(self, template_name):
            """Update all images that use the specified template"""
            if template_name not in self.templates:
                return

            template = self.templates[template_name]
            updated_count = 0  # Initialize updated_count here
    
            for entry in self.images:
                if entry.template_tag == template_name:
                    entry.target_w = template['width']
                    entry.target_h = template['height']
                    entry.corner_radius = template.get('corner_radius', 0)
                    updated_count += 1

            if updated_count > 0:
                self.recalc_layout()
                self.refresh_listbox()
                self.invalidate_cache()
                if self.preview_window and tk.Toplevel.winfo_exists(self.preview_window):
                    self.update_preview()
                messagebox.showinfo("Template Updated", f"Updated {updated_count} images with template '{template_name}'")



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
        ttk.Label(top_frame, text="Scale Factor:").grid(row=0, column=8, padx=5, sticky="e")
        ttk.Entry(top_frame, textvariable=self.scale_var, width=4).grid(row=0, column=9)
        ttk.Button(top_frame, text="Scale Collage", style="Accent.TButton", command=self.scale_collage).grid(row=0, column=10, padx=5)
        ttk.Button(top_frame, text="Preview", style="Accent.TButton", command=self.show_preview).grid(row=0, column=11, padx=5)
        ttk.Button(top_frame, text="Save", style="Accent.TButton", command=self.save_collage).grid(row=0, column=12, padx=5)
        ttk.Button(top_frame, text="Export Project", style="Accent.TButton", command=self.export_project).grid(row=0, column=13, padx=5)
        ttk.Button(top_frame, text="Import Project", style="Accent.TButton", command=self.import_project).grid(row=0, column=14, padx=5)
        ttk.Button(top_frame, text="Template", style="Accent.TButton", command=self.show_template_manager).grid(row=0, column=15, padx=5) 

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
            info = f"File: {entry.filename} | Orig: {entry.orig_w}x{entry.orig_h} | Target: {entry.target_w}x{entry.target_h} | Pos: ({x}, {y}) | Locked: {entry.locked}"
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
            # Skip auto layout for locked images
            if entry.locked:
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
            self.invalidate_cache() 

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
        self.invalidate_cache() 

    def edit_selected_image(self):
        sel_idx = self.img_listbox.curselection()
        if not sel_idx:
            messagebox.showinfo("No Selection", "Select an image to edit.")
            return
        entry = self.images[sel_idx[0]]
        self.open_image_dialog(entry.path, entry.orig_w, entry.orig_h, entry)
        self.invalidate_cache() 

    def remove_selected_image(self):
        sel_idx = self.img_listbox.curselection()
        if not sel_idx:
            return
        self.images.pop(sel_idx[0])
        self.recalc_layout()
        self.refresh_listbox()
        self.invalidate_cache() 

    # -------------------------------------------
    # Image Settings Dialog (Add/Edit)
    # -------------------------------------------
    def open_image_dialog(self, path, orig_w, orig_h, entry=None):
        dialog = tk.Toplevel(self)
        dialog.title("Image Settings")
        dialog.attributes("-alpha", WINDOW_ALPHA)
        dialog.configure(bg=PRIMARY_COLOR)
        dialog.geometry("450x600")  # Set explicit size
        dialog.resizable(True, True)  # Allow resizing
    
        ttk.Label(dialog, text=f"File: {os.path.basename(path)}").pack(anchor="w", padx=5, pady=2)
        ttk.Label(dialog, text=f"Original Size: {orig_w} x {orig_h}").pack(anchor="w", padx=5, pady=2)
    
        pos_info = "Current Positions:\n"
        for img in self.images:
            px, py = img.get_display_pos()
            pos_info += f"  {img.filename} -> ({px}, {py}), Locked: {img.locked}\n"
        ttk.Label(dialog, text=pos_info, justify=tk.LEFT).pack(anchor="w", padx=5, pady=2)
    
        frame = ttk.Frame(dialog, padding=5)
        frame.pack()
    
        # Template selection
        ttk.Label(frame, text="Template:").grid(row=0, column=0, padx=5, pady=2, sticky="e")
        template_var = tk.StringVar(value=entry.template_tag if entry and entry.template_tag else "")
        template_combo = ttk.Combobox(frame, textvariable=template_var, width=15, state="readonly")
        template_combo['values'] = list(self.templates.keys())
        template_combo.grid(row=0, column=1, padx=5, pady=2)
    
        ttk.Label(frame, text="Target Width:").grid(row=1, column=0, padx=5, pady=2, sticky="e")
        tw_entry = ttk.Entry(frame, width=6)
        tw_entry.grid(row=1, column=1, padx=5, pady=2)
        tw_entry.insert(0, str(entry.target_w) if entry else "400")
    
        ttk.Label(frame, text="Target Height:").grid(row=2, column=0, padx=5, pady=2, sticky="e")
        th_entry = ttk.Entry(frame, width=6)
        th_entry.grid(row=2, column=1, padx=5, pady=2)
        th_entry.insert(0, str(entry.target_h) if entry else "300")
    
        # Template application
        def apply_template():
            selected = template_var.get()
            if selected and selected in self.templates:
                template = self.templates[selected]
                tw_entry.delete(0, tk.END)
                th_entry.delete(0, tk.END)
                cr_entry.delete(0, tk.END)
                tw_entry.insert(0, str(template['width']))
                th_entry.insert(0, str(template['height']))
                cr_entry.insert(0, str(template.get('corner_radius', 0)))
    
        ttk.Button(frame, text="Apply Template", command=apply_template).grid(row=0, column=2, padx=5, pady=2)
    
        ttk.Label(frame, text="Corner Radius:").grid(row=3, column=0, padx=5, pady=2, sticky="e")
        cr_entry = ttk.Entry(frame, width=6)
        cr_entry.grid(row=3, column=1, padx=5, pady=2)
        cr_entry.insert(0, str(entry.corner_radius if entry else 0))
    
        ttk.Label(frame, text="Manual X (optional):").grid(row=4, column=0, padx=5, pady=2, sticky="e")
        mx_entry = ttk.Entry(frame, width=6)
        mx_entry.grid(row=4, column=1, padx=5, pady=2)
        if entry and entry.manual_x is not None:
            mx_entry.insert(0, str(entry.manual_x))
    
        ttk.Label(frame, text="Manual Y (optional):").grid(row=5, column=0, padx=5, pady=2, sticky="e")
        my_entry = ttk.Entry(frame, width=6)
        my_entry.grid(row=5, column=1, padx=5, pady=2)
        if entry and entry.manual_y is not None:
            my_entry.insert(0, str(entry.manual_y))
    
        lock_var = tk.BooleanVar(value=entry.locked if entry else False)
        lock_check = ttk.Checkbutton(frame, text="Lock this image", variable=lock_var)
        lock_check.grid(row=6, column=0, columnspan=2, pady=2)
    
        ttk.Label(frame, text="(Leave manual positions blank for auto–layout)").grid(row=7, column=0, columnspan=2, pady=2)
    
        btn_frame = ttk.Frame(dialog, padding=5)
        btn_frame.pack()
    
        def on_ok():
            try:
                tw = int(tw_entry.get())
                th = int(th_entry.get())
                corner_radius = int(cr_entry.get())
            except ValueError:
                messagebox.showwarning("Invalid Input", "Enter valid integers for target size and corner radius.")
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

            template_tag = template_var.get() if template_var.get() else None

            if entry:
                entry.target_w = tw
                entry.target_h = th
                entry.manual_x = manual_x
                entry.manual_y = manual_y
                entry.locked = lock_var.get()
                entry.corner_radius = corner_radius
                entry.template_tag = template_tag
            else:
                new_entry = ImageEntry(path, orig_w, orig_h, tw, th)
                new_entry.manual_x = manual_x
                new_entry.manual_y = manual_y
                new_entry.locked = lock_var.get()
                new_entry.corner_radius = corner_radius
                new_entry.template_tag = template_tag
                self.images.append(new_entry)
        
            self.recalc_layout()
            self.refresh_listbox()
            self.invalidate_cache() 
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
        self.invalidate_cache() 
        if self.preview_window and tk.Toplevel.winfo_exists(self.preview_window):
            self.update_preview()


    # -------------------------------------------
    # template management methods
    # -------------------------------------------
    def load_templates(self):
        """Load templates from file"""
        try:
            if os.path.exists("templates.json"):
                with open("templates.json", "r") as f:
                    self.templates = json.load(f)
        except Exception as e:
            print(f"Error loading templates: {e}")
            self.templates = {}
            self.invalidate_cache() 
    
    def save_templates(self):
        """Save templates to file"""
        try:
            with open("templates.json", "w") as f:
                json.dump(self.templates, f, indent=2)
        except Exception as e:
            print(f"Error saving templates: {e}")

    def show_template_manager(self):
        """Show template management dialog"""
        dialog = tk.Toplevel(self)
        dialog.title("Template Manager")
        dialog.attributes("-alpha", WINDOW_ALPHA)
        dialog.configure(bg=PRIMARY_COLOR)
        dialog.geometry("400x300")
    
        # Template list
        frame = ttk.Frame(dialog, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)
    
        ttk.Label(frame, text="Existing Templates:").pack(anchor="w")
    
        template_listbox = tk.Listbox(frame, height=8, bg=SECONDARY_COLOR, fg=TEXT_COLOR)
        template_listbox.pack(fill=tk.BOTH, expand=True, pady=5)
    
        def refresh_template_list():
            template_listbox.delete(0, tk.END)
            for name, data in self.templates.items():
                template_listbox.insert(tk.END, f"{name}: {data['width']}x{data['height']}")
    
        refresh_template_list()
    
        # Buttons
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X, pady=5)
    
        def add_template():
            add_dialog = tk.Toplevel(dialog)
            add_dialog.title("Add Template")
            add_dialog.configure(bg=PRIMARY_COLOR)

            ttk.Label(add_dialog, text="Template Name:").grid(row=0, column=0, padx=5, pady=5)
            name_entry = ttk.Entry(add_dialog, width=15)
            name_entry.grid(row=0, column=1, padx=5, pady=5)

            ttk.Label(add_dialog, text="Width:").grid(row=1, column=0, padx=5, pady=5)
            width_entry = ttk.Entry(add_dialog, width=15)
            width_entry.grid(row=1, column=1, padx=5, pady=5)

            ttk.Label(add_dialog, text="Height:").grid(row=2, column=0, padx=5, pady=5)
            height_entry = ttk.Entry(add_dialog, width=15)
            height_entry.grid(row=2, column=1, padx=5, pady=5)
    
            # Add corner radius field
            ttk.Label(add_dialog, text="Corner Radius:").grid(row=3, column=0, padx=5, pady=5)
            corner_entry = ttk.Entry(add_dialog, width=15)
            corner_entry.grid(row=3, column=1, padx=5, pady=5)
            corner_entry.insert(0, "0")  # Default value

            def save_template():
                name = name_entry.get().strip()
                try:
                    width = int(width_entry.get())
                    height = int(height_entry.get())
                    corner_radius = int(corner_entry.get())
                except ValueError:
                    messagebox.showwarning("Invalid Input", "Width, height, and corner radius must be integers.")
                    return

                if not name:
                    messagebox.showwarning("Invalid Input", "Template name cannot be empty.")
                    return
        
                # Include corner_radius in template data
                self.templates[name] = {"width": width, "height": height, "corner_radius": corner_radius}
                self.save_templates()
                refresh_template_list()
                self.invalidate_cache() 
                self.update_images_with_template(name)  
                add_dialog.destroy()

            ttk.Button(add_dialog, text="Save", command=save_template).grid(row=4, column=0, columnspan=2, pady=10)

        def refresh_template_list():
            template_listbox.delete(0, tk.END)
            for name, data in self.templates.items():
                corner_radius = data.get('corner_radius', 0)  # Default to 0 for backward compatibility
                template_listbox.insert(tk.END, f"{name}: {data['width']}x{data['height']}, R:{corner_radius}")
                self.invalidate_cache() 
    
        def remove_template():
            sel_idx = template_listbox.curselection()
            if not sel_idx:
                messagebox.showinfo("No Selection", "Select a template to remove.")
                return
        
            template_names = list(self.templates.keys())
            if sel_idx[0] < len(template_names):
                name = template_names[sel_idx[0]]
                if messagebox.askyesno("Confirm Delete", f"Delete template '{name}'?"):
                    del self.templates[name]
                    self.save_templates()
                    self.invalidate_cache() 
                    refresh_template_list()
    
        ttk.Button(btn_frame, text="Add Template", command=add_template).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Remove Template", command=remove_template).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Close", command=dialog.destroy).pack(side=tk.RIGHT, padx=5)

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
            if entry.corner_radius > 0:
                mask = create_rounded_mask(resized.width, resized.height, entry.corner_radius)
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
    # Preview Window (Interactive) with Zoom and Manual Position Editing
    # -------------------------------------------
    def show_preview(self):
        if not self.images:
            messagebox.showinfo("No Images", "Add images first.")
            return
        if self.preview_window and tk.Toplevel.winfo_exists(self.preview_window):
            self.preview_window.lift()
            return
        self.preview_zoom_factor = 1.0  # Reset zoom
        self.preview_window = tk.Toplevel(self)
        self.preview_window.title("Collage Preview")
        self.preview_window.attributes("-alpha", WINDOW_ALPHA)
        self.preview_window.configure(bg=PRIMARY_COLOR)
        top_bar = ttk.Frame(self.preview_window, padding=5)
        top_bar.pack(fill=tk.X)

        ttk.Button(top_bar, text="25%", style="Accent.TButton", command=lambda: self.set_zoom(0.25)).pack(side=tk.LEFT, padx=2)
        ttk.Button(top_bar, text="50%", style="Accent.TButton", command=lambda: self.set_zoom(0.5)).pack(side=tk.LEFT, padx=2)
        ttk.Button(top_bar, text="100%", style="Accent.TButton", command=lambda: self.set_zoom(1.0)).pack(side=tk.LEFT, padx=2)
        ttk.Button(top_bar, text="Zoom In", style="Accent.TButton", command=self.zoom_in).pack(side=tk.LEFT, padx=2)
        ttk.Button(top_bar, text="Zoom Out", style="Accent.TButton", command=self.zoom_out).pack(side=tk.LEFT, padx=2)
        ttk.Button(top_bar, text="Fit", style="Accent.TButton", command=self.fit_to_window).pack(side=tk.LEFT, padx=2)

        # Show zoom percentage
        self.zoom_label = ttk.Label(top_bar, text="100%", foreground=TEXT_COLOR)
        self.zoom_label.pack(side=tk.LEFT, padx=10)
        # Fit button
        ttk.Button(top_bar, text="Fit", style="Accent.TButton", command=self.fit_to_window).pack(side=tk.LEFT, padx=5)

        main_pane = ttk.PanedWindow(self.preview_window, orient=tk.HORIZONTAL)
        main_pane.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        canvas_frame = ttk.Frame(main_pane)
        self.canvas = tk.Canvas(canvas_frame, bg=SECONDARY_COLOR, highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        main_pane.add(canvas_frame, weight=3)

        self.details_panel = ttk.Frame(main_pane, padding=10)
        main_pane.add(self.details_panel, weight=1)

        self.details_label = ttk.Label(
            self.details_panel, 
            text="Image Info", 
            wraplength=200,  # Adjust if you want narrower or wider wrapping
            justify="left"
        )

        self.details_label.pack(anchor="n")
        # Info button (renamed from Edit)
        self.info_button = ttk.Button(self.details_panel, text="Info", style="Accent.TButton",
                                      command=self.edit_selected_from_preview)
        self.info_button.pack(anchor="n", pady=5)
        # Lock toggle button
        self.lock_button = ttk.Button(self.details_panel, text="Lock", style="Accent.TButton",
                                      command=self.toggle_lock_selected)
        self.lock_button.pack(anchor="n", pady=5)
        # Edit button:
        self.edit_preview_button = ttk.Button(self.details_panel, text="Edit Selected", style="Accent.TButton",
                                      command=self.edit_selected_from_preview_dialog)
        self.edit_preview_button.pack(anchor="n", pady=5)
        # Manual position editing: two entry fields and a Set button
        pos_frame = ttk.Frame(self.details_panel, padding=5)
        pos_frame.pack(anchor="n", pady=5)
        ttk.Label(pos_frame, text="X:").grid(row=0, column=0, padx=2, pady=2)
        self.manual_x_entry = ttk.Entry(pos_frame, width=6)
        self.manual_x_entry.grid(row=0, column=1, padx=2, pady=2)
        ttk.Label(pos_frame, text="Y:").grid(row=1, column=0, padx=2, pady=2)
        self.manual_y_entry = ttk.Entry(pos_frame, width=6)
        self.manual_y_entry.grid(row=1, column=1, padx=2, pady=2)
        ttk.Button(pos_frame, text="Set", style="Accent.TButton", command=self.set_manual_position).grid(row=2, column=0, columnspan=2, pady=5)

        self.preview_items = {}
        self.selected_preview_entry = None
        self.tooltip = Tooltip(self.canvas)
        self.canvas.bind("<Configure>", self.on_canvas_configure)
        self.invalidate_cache() 
        self.update_preview()

    def set_zoom(self, zoom_level):
        self.canvas_scale_factor = max(0.1, min(zoom_level, 5.0))
        self.canvas_offset_x = 0  # Reset pan when using presets
        self.canvas_offset_y = 0
        self.update_preview()

    def invalidate_cache(self):
        """Call this whenever layout changes to force cache regeneration"""
        self.cached_collage = None
        self.cached_collage_settings = None

    def on_canvas_configure(self, event):
        self.center_preview_image()

    def center_preview_image(self):
        items = self.canvas.find_withtag("preview_image")
        if items:
            canvas_width = self.canvas.winfo_width()
            canvas_height = self.canvas.winfo_height()
            self.canvas.coords(items[0], canvas_width/2, canvas_height/2)

    def edit_selected_from_preview_dialog(self):
        """Open full edit dialog for selected image from preview"""
        if self.selected_preview_entry:
            self.open_image_dialog(self.selected_preview_entry.path, 
                                  self.selected_preview_entry.orig_w, 
                                  self.selected_preview_entry.orig_h, 
                                  self.selected_preview_entry)
        # Refresh preview after editing
        if self.preview_window and tk.Toplevel.winfo_exists(self.preview_window):
            self.update_preview()

    def update_preview(self):
        # Check if we need to regenerate the cached collage
        current_settings = (
            self.collage_width_var.get(),
            self.collage_height_var.get(), 
            self.border_var.get(),
            self.bg_color_var.get(),
            len(self.images),
            tuple((img.target_w, img.target_h, img.get_display_pos(), img.locked) for img in self.images)
        )
    
        if self.cached_collage is None or self.cached_collage_settings != current_settings:
            print("Regenerating collage cache...")
            self.cached_collage = self.build_collage()
            self.cached_collage_settings = current_settings
            if self.cached_collage is None:
                return
    
        # Use cached collage and scale it
        collage_img = self.cached_collage
        cw, ch = collage_img.size
    
        # Calculate display size based on canvas scale factor
        display_w = int(cw * self.canvas_scale_factor)
        display_h = int(ch * self.canvas_scale_factor)
    
        # Only resize if we need to (avoid unnecessary operations)
        if self.canvas_scale_factor != 1.0:
            preview_img = collage_img.resize((display_w, display_h), Image.LANCZOS)
        else:
            preview_img = collage_img
    
        self.zoom_label.config(text=f"{int(self.canvas_scale_factor*100)}%")
        self.preview_photo = ImageTk.PhotoImage(preview_img)
    
        # Clear and redraw
        self.canvas.delete("all")
        canvas_width = self.canvas.winfo_width() or display_w
        canvas_height = self.canvas.winfo_height() or display_h
    
        # Apply pan offset
        img_x = canvas_width/2 + self.canvas_offset_x
        img_y = canvas_height/2 + self.canvas_offset_y
    
        self.canvas.create_image(img_x, img_y, anchor="center", image=self.preview_photo, tags="preview_image")
    
        # Update interactive rectangles
        self.update_preview_rectangles(display_w, display_h, img_x - display_w/2, img_y - display_h/2)

    def update_preview_rectangles(self, display_w, display_h, offset_x, offset_y):
        self.preview_items.clear()
    
        for idx, entry in enumerate(self.images):
            pos = entry.get_display_pos()
            if pos[0] is None or pos[1] is None:
                continue
        
            x, y = pos
            x_s = x * self.canvas_scale_factor + offset_x
            y_s = y * self.canvas_scale_factor + offset_y
            w_s = entry.target_w * self.canvas_scale_factor
            h_s = entry.target_h * self.canvas_scale_factor
        
            rect = self.canvas.create_rectangle(x_s, y_s, x_s + w_s, y_s + h_s,
                                            outline="", width=2,
                                            tags=("img", f"img_{idx}"))
            self.preview_items[rect] = entry
            self.canvas.tag_bind(rect, "<Enter>", self.on_img_enter)
            self.canvas.tag_bind(rect, "<Leave>", self.on_img_leave)
            self.canvas.tag_bind(rect, "<Button-1>", self.on_img_click)

    def zoom_in(self):
        self.canvas_scale_factor = min(self.canvas_scale_factor * 1.5, 5.0)  # Limit to 500%
        self.update_preview()

    def zoom_out(self):
        self.canvas_scale_factor = max(self.canvas_scale_factor / 1.5, 0.1)  # Limit to 10%
        self.update_preview()

    def fit_to_window(self):
        if self.cached_collage is None:
            return
    
        cw, ch = self.cached_collage.size
        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()
    
        if canvas_width <= 0 or canvas_height <= 0:
            return
    
        scale_x = (canvas_width - 20) / cw  # Leave 20px margin
        scale_y = (canvas_height - 20) / ch
        self.canvas_scale_factor = min(scale_x, scale_y)
        self.canvas_offset_x = 0  # Reset pan
        self.canvas_offset_y = 0
        self.update_preview()

    def on_img_enter(self, event):
        item = self.canvas.find_withtag("current")
        if item:
            entry = self.preview_items.get(item[0])
            if entry:
                x, y = entry.get_display_pos()
                text = (f"File: {entry.filename}\n"
                        f"Orig: {entry.orig_w}x{entry.orig_h}\n"
                        f"Target: {entry.target_w}x{entry.target_h}\n"
                        f"Pos: ({x}, {y})\n"
                        f"Locked: {entry.locked}")
                self.tooltip.showtip(text)

    def on_img_leave(self, event):
        self.tooltip.hidetip()

    def on_img_click(self, event):
        item = self.canvas.find_withtag("current")
        if item:
            entry = self.preview_items.get(item[0])
            if entry:
                self.canvas.delete("highlight")
                pos = entry.get_display_pos()
                final_scale = ( (self.canvas.winfo_width() / max(int(self.collage_width_var.get()),1)) * self.preview_zoom_factor )
                canvas_width = self.canvas.winfo_width()
                canvas_height = self.canvas.winfo_height()
                offset_x = canvas_width/2 - (int(self.collage_width_var.get()) * final_scale)/2
                offset_y = canvas_height/2 - (int(self.collage_height_var.get()) * final_scale)/2
                x_s = pos[0] * final_scale + offset_x
                y_s = pos[1] * final_scale + offset_y
                w_s = entry.target_w * final_scale
                h_s = entry.target_h * final_scale
                self.canvas.create_rectangle(x_s, y_s, x_s + w_s, y_s + h_s,
                                             outline=ACCENT_COLOR, width=3, tags="highlight")
                details = (f"File: {entry.filename}\n"
                           f"Original: {entry.orig_w} x {entry.orig_h}\n"
                           f"Target: {entry.target_w} x {entry.target_h}\n"
                           f"Position: ({pos[0]}, {pos[1]})\n"
                           f"Locked: {entry.locked}")
                self.details_label.config(text=details)
                self.selected_preview_entry = entry
                # Populate manual position entries with current values:
                self.manual_x_entry.delete(0, tk.END)
                self.manual_y_entry.delete(0, tk.END)
                self.manual_x_entry.insert(0, str(pos[0]) if pos[0] is not None else "")
                self.manual_y_entry.insert(0, str(pos[1]) if pos[1] is not None else "")

    def edit_selected_from_preview(self):
        # Renamed from "Edit" to "Info" – this simply shows the info.
        if self.selected_preview_entry:
            pos = self.selected_preview_entry.get_display_pos()
            details = (f"File: {self.selected_preview_entry.filename}\n"
                       f"Original: {self.selected_preview_entry.orig_w} x {self.selected_preview_entry.orig_h}\n"
                       f"Target: {self.selected_preview_entry.target_w} x {self.selected_preview_entry.target_h}\n"
                       f"Position: ({pos[0]}, {pos[1]})\n"
                       f"Locked: {self.selected_preview_entry.locked}")
            messagebox.showinfo("Image Info", details)

    def toggle_lock_selected(self):
        # Toggle lock for selected image from preview.
        if self.selected_preview_entry:
            self.selected_preview_entry.locked = not self.selected_preview_entry.locked
            state = "Locked" if self.selected_preview_entry.locked else "Unlocked"
            messagebox.showinfo("Lock Toggled", f"{self.selected_preview_entry.filename} is now {state}.")
            self.refresh_listbox()
            self.invalidate_cache() 
            self.update_preview()

    def set_manual_position(self):
        # Set manual x and y for the selected image.
        if not self.selected_preview_entry:
            messagebox.showwarning("No Image Selected", "Click on an image to select it first.")
            return
        try:
            new_x = int(self.manual_x_entry.get())
            new_y = int(self.manual_y_entry.get())
        except ValueError:
            messagebox.showwarning("Invalid Input", "Enter valid integers for manual X and Y.")
            return
        self.selected_preview_entry.manual_x = new_x
        self.selected_preview_entry.manual_y = new_y
        # When manually set, also lock the image automatically.
        self.selected_preview_entry.locked = True
        self.refresh_listbox()
        self.invalidate_cache() 
        self.update_preview()

    # -------------------------------------------
    # Export Project (Embed all image data)
    # -------------------------------------------
    def export_project(self):
        save_path = filedialog.asksaveasfilename(
            defaultextension=".elf",
            filetypes=[("Collage Project", "*.elf"), ("All Files", "*.*")]
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
                    "locked": entry.locked,
                    "filename": entry.filename,
                    "template_tag": entry.template_tag,
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
            filetypes=[("Collage Project", "*.elf"), ("All Files", "*.*")]
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
                new_entry.locked = img_info.get("locked", False)
                new_entry.template_tag = img_info.get("template_tag", None)  
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
