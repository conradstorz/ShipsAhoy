from ships_ahoy.renderer import BitmapFont, render_text, scroll_frame

DISPLAY_W = 20  # small display for tests
DISPLAY_H = 8

def test_render_text_returns_pixel_grid():
    grid = render_text("AB", color=(255, 255, 255), width=DISPLAY_W, height=DISPLAY_H)
    assert isinstance(grid, list)
    assert len(grid) == DISPLAY_H
    assert all(len(row) == DISPLAY_W for row in grid)

def test_render_text_pixel_is_rgb_tuple():
    grid = render_text("A", color=(255, 0, 0), width=DISPLAY_W, height=DISPLAY_H)
    px = grid[0][0]
    assert isinstance(px, tuple)
    assert len(px) == 3

def test_render_text_space_is_all_black():
    grid = render_text(" ", color=(255, 255, 255), width=DISPLAY_W, height=DISPLAY_H)
    for row in grid:
        for px in row:
            assert px == (0, 0, 0)

def test_render_text_letter_has_some_lit_pixels():
    # 'A' should have at least one non-black pixel
    grid = render_text("A", color=(255, 255, 255), width=DISPLAY_W, height=DISPLAY_H)
    lit = sum(1 for row in grid for px in row if px != (0, 0, 0))
    assert lit > 0

def test_render_text_color_respected():
    grid = render_text("A", color=(100, 200, 50), width=DISPLAY_W, height=DISPLAY_H)
    colors = {px for row in grid for px in row if px != (0, 0, 0)}
    assert (100, 200, 50) in colors

def test_scroll_frame_zero_offset():
    full = render_text("HELLO", color=(255, 255, 255), width=100, height=DISPLAY_H)
    frame = scroll_frame(full, offset=0, display_width=DISPLAY_W)
    assert len(frame) == DISPLAY_H
    assert all(len(row) == DISPLAY_W for row in frame)
    assert frame[0] == full[0][:DISPLAY_W]

def test_scroll_frame_nonzero_offset():
    full = render_text("HELLO", color=(255, 255, 255), width=100, height=DISPLAY_H)
    frame0 = scroll_frame(full, offset=0, display_width=DISPLAY_W)
    frame6 = scroll_frame(full, offset=6, display_width=DISPLAY_W)
    assert frame0 != frame6

def test_scroll_frame_past_end_is_black():
    full = render_text("A", color=(255, 255, 255), width=100, height=DISPLAY_H)
    # offset beyond full width: all black
    frame = scroll_frame(full, offset=9999, display_width=DISPLAY_W)
    for row in frame:
        assert all(px == (0, 0, 0) for px in row)
