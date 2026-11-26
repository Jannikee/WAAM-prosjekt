import math

b_st = 20
t_T = 20
L_arm = 20
sigma_u_Al = 140
sigma_y_st = 345
n = 2
t = 20

b_sp = b_st
b_v = 2 * 1.15 * L_arm + b_st
a = L_arm

F = b_st * t_T * sigma_u_Al
sigma_tillatt = sigma_y_st / n
tau_tillatt = sigma_tillatt / math.sqrt(3)

L_skulder = (b_v - b_sp) / 2
e_s = L_skulder - a / 3

# skulder
M_s = F / 2 * e_s
h_s = math.sqrt(6 * M_s / (sigma_tillatt * t))

# bein, prøver seg fram
N_b = F / 2
b_b = 1
while True:
    M_b = F / 2 * (e_s + b_b / 2)
    sigma_b = N_b / (b_b * t) + 6 * M_b / (t * b_b**2)
    if sigma_b <= sigma_tillatt:
        break
    b_b += 0.1

# bunnbjelke
M_t = M_s
h_t = math.sqrt(6 * M_t / (sigma_tillatt * t))

h_s_valgt = math.ceil(h_s)
b_b_valgt = math.ceil(b_b)
h_t_valgt = math.ceil(h_t)

tau = 1.5 * (F / 2) / (min(h_s_valgt, h_t_valgt) * t)

print(f"F = {F:.0f} N")
print(f"sigma_tillatt = {sigma_tillatt:.1f} MPa")
print(f"e_s = {e_s:.1f} mm")
print(f"M_s = M_t = {M_s:.0f} Nmm")
print()
print(f"h_s: min {h_s:.1f} -> {h_s_valgt} mm")
print(f"b_b: min {b_b:.1f} -> {b_b_valgt} mm")
print(f"h_t: min {h_t:.1f} -> {h_t_valgt} mm")
print()
print(f"tau = {tau:.0f} MPa (maks {tau_tillatt:.0f}) {'OK' if tau <= tau_tillatt else 'IKKE OK'}")
print(f"ytre bredde = {b_v + 2 * b_b_valgt:.0f} mm")