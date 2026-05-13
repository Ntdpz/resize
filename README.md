# Auto Watermark & Resize Tool

Windows desktop app for batch watermarking images with selectable output size mode: resize to 1280px width or keep original dimensions.

## Features

- Select a transparent PNG logo file.
- Select either a single image or a folder containing `.jpg`, `.jpeg`, or `.png` images.
- Choose output mode between `Resize 1280px` and `Original Size`.
- In `Resize 1280px` mode, resize every image to 1280px width while preserving aspect ratio.
- In `Original Size` mode, keep the source dimensions and only apply the watermark.
- Apply different default watermark positions for landscape and portrait images.
- Adjust watermark size plus horizontal and vertical offsets from the UI.
- Preview the logo, the selected source image, and the final output before processing.
- Drag the logo directly on the `Result` preview to change position.
- Use the mouse wheel over the logo on the `Result` preview to resize it.
- Save output into a sibling folder named `[OriginalFolder]_Processed` without overwriting source files.
- Show progress and keep the UI responsive during batch processing.

## Run From Source

```powershell
py -3 -m pip install -r requirements.txt
py -3 app.py
```

## Build EXE

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\build_exe.ps1
```

Build output will be created under `dist\AutoWatermark\`.
The executable file is `dist\AutoWatermark.exe`.

## How To Use

1. Open the application.
2. Click `เลือกไฟล์โลโก้ .png` and choose the company logo.
3. Choose `folder` or `single` mode.
4. Click the source picker and choose an image folder or one image file.
5. Review the `Logo`, `Source`, and `Result` preview panes.
6. Choose `Resize 1280px` or `Original Size` in the `Output Size` control.
7. Drag the logo on the `Result` preview or use the controls to adjust position.
8. Use the mouse wheel over the logo in the `Result` preview or the size slider to resize it.
9. Click `START / เริ่มประมวลผล`.
10. When finished, click `เปิดโฟลเดอร์ผลลัพธ์`.

## Project Structure

- `app.py` - app entry point
- `core/` - image processing logic and batch orchestration
- `ui/` - CustomTkinter desktop UI
- `build/AutoWatermark.spec` - PyInstaller specification
- `build_exe.ps1` - build helper script
