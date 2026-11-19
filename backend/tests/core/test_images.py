"""Image processing: metadata stripped, downscaled, HEIC converted, junk refused."""

import io
from pathlib import Path

import pytest
from PIL import Image, PngImagePlugin

from app.services.images import ImageError, process_image, resolve_stored, store_image

MB = 1024 * 1024
GPS_IFD = 0x8825
ORIENTATION = 0x0112


def jpeg_with_location(size: tuple[int, int] = (200, 100), orientation: int = 1) -> bytes:
    image = Image.new("RGB", size, (200, 30, 30))
    exif = Image.Exif()
    exif[0x010F] = "PhoneMaker"  # camera make
    exif[ORIENTATION] = orientation
    exif.get_ifd(GPS_IFD).update({1: "N", 2: (41.0, 2.0, 30.0), 3: "E", 4: (29.0, 1.0, 5.0)})
    out = io.BytesIO()
    image.save(out, format="JPEG", exif=exif)
    return out.getvalue()


def opened(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))


def test_location_and_camera_data_are_removed() -> None:
    raw = jpeg_with_location()
    assert opened(raw).getexif().get_ifd(GPS_IFD)  # the fixture really has a location

    result = process_image(raw, max_bytes=20 * MB, max_edge=1600)

    image = opened(result.data)
    assert result.mime == "image/jpeg"
    assert dict(image.getexif()) == {}
    assert "exif" not in image.info
    assert b"PhoneMaker" not in result.data


def test_orientation_is_applied_before_exif_is_dropped() -> None:
    raw = jpeg_with_location(size=(200, 100), orientation=6)  # "rotate 90" as shot

    result = process_image(raw, max_bytes=20 * MB, max_edge=1600)

    assert (result.width, result.height) == (100, 200)


def test_long_edge_is_scaled_down() -> None:
    out = io.BytesIO()
    Image.new("RGB", (4000, 3000), "white").save(out, format="JPEG")

    result = process_image(out.getvalue(), max_bytes=20 * MB, max_edge=1600)

    assert (result.width, result.height) == (1600, 1200)
    assert opened(result.data).size == (1600, 1200)


def test_heic_becomes_jpeg() -> None:
    out = io.BytesIO()
    Image.new("RGB", (300, 200), (10, 120, 200)).save(out, format="HEIF")
    assert opened(out.getvalue()).format == "HEIF"

    result = process_image(out.getvalue(), max_bytes=20 * MB, max_edge=1600)

    assert result.mime == "image/jpeg"
    assert opened(result.data).format == "JPEG"
    assert (result.width, result.height) == (300, 200)


def test_png_screenshot_stays_png_without_text_chunks() -> None:
    info = PngImagePlugin.PngInfo()
    info.add_text("Author", "someone@example.com")
    out = io.BytesIO()
    Image.new("RGBA", (120, 80), (0, 0, 0, 0)).save(out, format="PNG", pnginfo=info)

    result = process_image(out.getvalue(), max_bytes=20 * MB, max_edge=1600)

    assert result.mime == "image/png"
    assert b"someone@example.com" not in result.data
    assert opened(result.data).mode == "RGBA"


@pytest.mark.parametrize(
    ("raw", "max_bytes", "code"),
    [
        (b"not an image at all", 20 * MB, "not_an_image"),
        (b"x" * 2048, 1024, "too_large"),
    ],
)
def test_refused(raw: bytes, max_bytes: int, code: str) -> None:
    with pytest.raises(ImageError) as error:
        process_image(raw, max_bytes=max_bytes, max_edge=1600)

    assert error.value.code == code


def test_stored_paths_stay_inside_the_upload_dir(tmp_path: Path) -> None:
    import datetime as dt

    result = process_image(jpeg_with_location(), max_bytes=20 * MB, max_edge=1600)
    relative = store_image(result, tmp_path, dt.datetime(2026, 11, 19, tzinfo=dt.UTC))

    assert relative.startswith("2026/11/")
    assert resolve_stored(tmp_path, relative).read_bytes() == result.data
    with pytest.raises(ImageError):
        resolve_stored(tmp_path, "../../etc/passwd")
