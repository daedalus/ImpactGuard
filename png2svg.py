import vtracer

input_path = "logo.png"
output_svg = "logo.svg"

vtracer.convert_image_to_svg_py(
    input_path,
    output_svg,
    colormode="color",
    hierarchical="stacked",
    mode="spline",
    filter_speckle=1,  # minimal noise removal
    color_precision=10,  # maximum color precision
    layer_difference=8,  # lower = preserve more detail
    corner_threshold=180,  # maximum smoothness
    length_threshold=3.5,  # minimum for fine detail
    max_iterations=50,  # maximum optimization
    splice_threshold=20,  # lower = less splicing
    path_precision=10,  # maximum coordinate precision
)

print(f"Created maximum quality SVG: {output_svg}")
