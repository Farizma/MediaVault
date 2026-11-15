// Media Vault: a VR video (180 / 360 equirectangular, or fisheye; mono, side by side or top-bottom) shown as a flat
// 16:9 view of one eye that you look around in. The player changes yaw, pitch and fov while it plays
// (glsl-shader-opts), so dragging needs no rebuild. Needs --vo=gpu-next.

//!PARAM proj
//!DESC 0 = 180 equirectangular, 1 = 360 equirectangular, 2 = fisheye
//!TYPE int
//!MINIMUM 0
//!MAXIMUM 2
0

//!PARAM stereo
//!DESC 0 = mono, 1 = side by side (left eye used), 2 = top-bottom (top eye used)
//!TYPE int
//!MINIMUM 0
//!MAXIMUM 2
1

//!PARAM lens
//!DESC fisheye lens field of view, degrees
//!TYPE float
190.0

//!PARAM yaw
//!TYPE float
0.0

//!PARAM pitch
//!TYPE float
0.0

//!PARAM fov
//!DESC horizontal field of view of the view, degrees
//!TYPE float
100.0

//!HOOK MAIN
//!BIND HOOKED
//!WIDTH 2560
//!HEIGHT 1440
//!DESC Media Vault VR view

vec4 hook() {
    const float PI_ = 3.14159265358979;
    vec2 p = HOOKED_pos * 2.0 - 1.0;
    float t = tan(radians(fov) * 0.5);
    vec3 d = normalize(vec3(p.x * t, -p.y * t * (9.0 / 16.0), 1.0));
    float cp = cos(radians(pitch)), sp = sin(radians(pitch));
    d = vec3(d.x, d.y * cp + d.z * sp, -d.y * sp + d.z * cp);
    float cy = cos(radians(yaw)), sy = sin(radians(yaw));
    d = vec3(d.x * cy + d.z * sy, d.y, -d.x * sy + d.z * cy);
    vec2 e;
    if (proj == 2) {
        float theta = acos(clamp(d.z, -1.0, 1.0));
        float r = theta / radians(lens * 0.5) * 0.5;
        float l = length(d.xy);
        vec2 dir = l > 1e-6 ? d.xy / l : vec2(0.0);
        e = vec2(0.5 + r * dir.x, 0.5 - r * dir.y);
    } else {
        float lon = atan(d.x, d.z);
        float lat = asin(clamp(d.y, -1.0, 1.0));
        e = vec2(lon / (proj == 1 ? 2.0 * PI_ : PI_) + 0.5, 0.5 - lat / PI_);
    }
    if (e.x < 0.0 || e.x > 1.0 || e.y < 0.0 || e.y > 1.0)
        return vec4(0.0, 0.0, 0.0, 1.0);
    if (stereo == 1)
        e.x *= 0.5;
    else if (stereo == 2)
        e.y *= 0.5;
    return HOOKED_tex(e);
}
