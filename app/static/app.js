// Bureau des Traders — scène pixel art pilotée par les événements du serveur.
const W = 392, H = 266;
const cv = document.getElementById("c"), ctx = cv.getContext("2d");
const calque = document.getElementById("calque"), cadre = document.getElementById("cadre");
let S = 3;

// ---------- Agents ----------
const ROLES = {
  directeur: "Orchestre toute l'équipe et décide de l'ordre du travail.",
  scanner: "Scanne des milliers de graphiques pour trouver des configurations.",
  news: "Surveille les titres et les dépôts 8-K de chaque action suivie.",
  entry: "Observe une configuration bougie par bougie et dit quand entrer.",
  exit: "Place le stop et l'objectif avant d'entrer.",
  timemachine: "Rejoue le trade 10 000 fois pour donner les vraies chances.",
  budget: "Calcule combien d'actions acheter selon ton budget et ta perte max.",
  risk: "Bloque tout ce qui dépasse tes règles.",
  broker: "Prépare le ticket d'ordre. N'envoie jamais rien sans toi.",
  alerts: "Sonne quand un prix, un stop ou la cloche d'ouverture arrive.",
  analyst: "Lit les résultats trimestriels sur SEC EDGAR.",
  pelosi: "Suit les achats d'actions déclarés par les membres du Congrès.",
  fouineuse: "Fouille Yahoo Finance : tendances, plus fortes hausses, volumes anormaux.",
  crieur: "Écoute la foule : les actions les plus citées sur StockTwits et Reddit.",
};
// look : cheveux, peau, couleur du costume / de la robe, H ou F, accessoire
const LOOK = {
  directeur:  ["#2b1d14", "#f1c9a5", "#2d2a4a", "H", "pochette"],
  scanner:    ["#5a3a22", "#e8b48a", "#2f9e5a", "H", "lunettes"],
  news:       ["#c94b2b", "#f5d0b0", "#e0507a", "F", "chapeau"],
  entry:      ["#111111", "#a8704a", "#e0823a", "H", "casquette"],
  exit:       ["#e8d26a", "#f3cfb0", "#3a6ad8", "F", ""],
  timemachine:["#d9d9e8", "#efc6a8", "#8a4fd0", "H", "lunettes"],
  budget:     ["#3a2a1a", "#c98e64", "#f2f2f2", "H", ""],
  risk:       ["#222222", "#7a5034", "#b02a3a", "H", "casquette"],
  broker:     ["#6b4a2a", "#f0c8a0", "#1e6b6b", "H", ""],
  alerts:     ["#ff9a3c", "#f5d2b5", "#f0c02a", "F", ""],
  analyst:    ["#2a2a3a", "#d9a47c", "#c03aa0", "F", "lunettes"],
  pelosi:     ["#9a9aa8", "#f2cfb4", "#1a1a1a", "H", "chapeau"],
  fouineuse:  ["#6a3ad0", "#f0c8a8", "#2ab0b0", "F", "lunettes"],
  crieur:     ["#c8501a", "#d9a47c", "#a07a2a", "H", ""],
};
// shortcut: couleurs #rrggbb uniquement
const shade = (c, f) => "#" + [1, 3, 5].map(i => Math.min(255, Math.round(parseInt(c.slice(i, i + 2), 16) * f)).toString(16).padStart(2, "0")).join("");
// ---------- Plan de l'étage ----------
// Rangée 1 : équipes Veille et Plan de trade (porte en bas) · couloir 1 · rangée 2 : équipe Exécution (porte en haut)
// + passage vertical · couloir 2 · rangée 3 : bureau du Directeur + coin détente.
const PW = 16, PH = 22, ASSIS_Y = 15;
const C1 = 70, C2 = 166, LIAISON = 356;      // y des couloirs (haut du perso), x du passage vertical
const POSTE = 37;                            // largeur d'un poste de travail
// Les agents qui enchaînent la même tâche partagent un grand bureau d'équipe.
const EQUIPES = [
  { id: "veille", nom: "ÉQUIPE VEILLE", x0: 0, y0: 0, w: 240, porte: "bas", sol: "#4a5a7a", membres: ["scanner", "news", "analyst", "pelosi", "fouineuse", "crieur"] },
  { id: "plan", nom: "ÉQUIPE PLAN DE TRADE", x0: 240, y0: 0, w: 152, porte: "bas", sol: "#4a6a5a", membres: ["entry", "exit", "timemachine"] },
  { id: "execution", nom: "ÉQUIPE EXÉCUTION & RISQUE", x0: 0, y0: 96, w: 336, porte: "haut", sol: "#6a4a55", membres: ["budget", "risk", "broker", "alerts"] },
];
const SALLES = {};
for (const e of EQUIPES) {
  Object.assign(e, { type: "bureau", h: 74, allee: e.x0 + 1, couloir: 1, dehors: [e.x0 + 1, C1],
    dedans: [e.x0 + 1, e.porte === "bas" ? e.y0 + 50 : e.y0 + 4] });
  e.membres.forEach((id, i) => {
    const bx = e.x0 + 16 + i * POSTE; // x de la table
    SALLES[id] = { salle: e, bx, y0: e.y0, siege: [bx + 4, e.y0 + 23], visite: [bx + 10, e.y0 + 47], visite2: [bx - 8, e.y0 + 47],
      cx: bx + 13, haut: e.y0 + 38, etiquette: [bx + 12, e.y0 + 15] };
  });
}
SALLES.directeur = { id: "directeur", type: "bureau", x0: 0, y0: 192, w: 168, h: 74, porte: "haut", allee: 4,
  dedans: [4, 196], dehors: [4, C2], couloir: 2, siege: [76, 215], visite: [100, 240], visite2: [122, 240],
  cx: 84, haut: 230, etiquette: [84, 208] };
const DETENTE = { id: "detente", type: "detente", x0: 168, y0: 192, w: 224, h: 74, porte: "haut",
  dedans: [220, 198], dehors: [220, C2], couloir: 2, rang: 218 };
const LISTE_SALLES = [...EQUIPES, SALLES.directeur, DETENTE];
const PLACES = {
  snack: [171, 214], soda: [187, 214], cafe: [203, 216],
  canape0: [232, 232], canape1: [252, 232], canape2: [272, 232], pouf: [310, 226],
};
const PISTE = [[220, 214], [240, 220], [260, 214], [280, 220], [300, 214]];

const agents = {};
function creer(id) {
  const s = SALLES[id];
  agents[id] = { id, nom: id, bureau: s, cx: s.cx, haut: s.haut, x: s.siege[0], y: s.siege[1], chemin: [], etat: "assis",
    travail: false, statut: null, sortie: [], pas: 0, anim: Math.random() * 10, vitesse: id === "directeur" ? 1.2 : 0.95 };
}
["directeur", ...EQUIPES.flatMap(e => e.membres)].forEach(creer);

// ---------- Sprites (figurines) ----------
const TETE = [
  "....HHHHHHHH....", "..HHHHHHHHHHHH..", ".HHHHHHHHHHHHHH.", ".HHHHHHHHHHHHHH.",
  ".HSSSSSSSSSSSSH.", ".SSSSSSSSSSSSSS.", ".SSWESSSSSSWESS.", ".SSEESSSSSSEESS.",
  ".SSEESSSSSSEESS.", ".SKSSSSSSSSSSKS.", ".SSSSSSSSSSSSSS.", "..SSSSSSSSSSSS..", "....SSSSSSSS....",
];
// Garçons : costume ouvert sur une chemise blanche (T), revers (L), bouton (O). Filles : robe cintrée, ceinture (D).
const CORPS = {
  H: [".....CCTTCC.....", "....CCLTTLCC....", "...SCCLTTLCCS...", "...SCCCCOCCCS...", "....CCCCCCCC...."],
  F: [".....CSSSSC.....", "....CCCSSCCC....", "...SCCCCCCCCS...", "...SDDDDDDDDS...", "...CCCCCCCCCC..."],
};
const JAMBES = {
  H: {
    debout: ["....PPPPPPPP....", "....PPP..PPP....", "....PPP..PPP....", "....BBB..BBB...."],
    pasA:   ["....PPPPPPPP....", "....PPP..PPP....", "...PPP....PPP...", "...BBB....BBB..."],
    pasB:   ["....PPPPPPPP....", ".....PPPPPP.....", ".....PPPPPP.....", ".....BBBBBB....."],
  },
  F: { // robe évasée, jambes fines, escarpins à talons
    debout: ["..CCCCCCCCCCCC..", "...DCCCCCCCCD...", ".....S....S.....", "....BBb..bBB...."],
    pasA:   ["..CCCCCCCCCCCC..", "...DCCCCCCCCD...", "....S......S....", "...BBb....bBB..."],
    pasB:   ["..CCCCCCCCCCCC..", "...DCCCCCCCCD...", "......S..S......", ".....Bb..bB....."],
  },
};
const assise = a => a.etat === "assis" || a.etat === "pouf";
function sprite(a, t) {
  const [hair, peau, haut, genre, acc] = LOOK[a.id], fille = genre === "F";
  const pal = { H: hair, S: peau, E: "#120c18", W: "#ffffff", K: "#f29a9a", C: haut,
    T: fille ? haut : "#f4f0ff", L: shade(haut, 0.7), O: shade(haut, 0.5), D: shade(haut, 0.68), P: shade(haut, 0.62),
    B: fille ? "#c0203a" : "#1a1420", b: "#5a0a1a", Q: "#ffcc4d", G: "#111", R: "#7a3a1a", Y: "#2a2a2a" };
  const JB = JAMBES[genre];
  let rows = [...TETE, ...CORPS[genre]];
  if (fille) { // cheveux longs et cils
    for (let r = 4; r <= 11; r++) rows[r] = "H" + rows[r].slice(1, 15) + "H";
    rows[12] = ".HHHSSSSSSSSHHH."; rows[6] = rows[6].slice(0, 2) + "E" + rows[6].slice(3, 13) + "E" + rows[6].slice(14);
  }
  if (assise(a)) {
    rows = rows.concat(JB.debout);
    if (a.travail && Math.floor(t / 6) % 2) { rows[14] = "....CCCTTCCC...."; rows[15] = "...SSCCCCCCSS..."; }
    if (a.activite === "musique" && Math.floor(t / 24) % 2) { rows[14] = "..S.CCCTTCCC...."; rows[13] = "..S..CCCCCC....."; }
  } else rows = rows.concat(a.etat === "marche" ? (Math.floor(a.pas / 7) % 2 ? JB.pasA : JB.pasB) : JB.debout);
  if (acc === "pochette" && !a.dos) rows[15] = rows[15].slice(0, 10) + "Q" + rows[15].slice(11);
  if (a.activite === "fete" && a.etat === "debout") {
    const g = Math.floor(t / 14) % 2;
    rows[12] = g ? "..S.SSSSSSSS...." : "....SSSSSSSS.S..";
    rows[13] = g ? "..S..CCCCCC....." : ".....CCCCCC..S..";
    rows[14] = g ? "...SCCCTTCCC...." : "....CCCTTCCCS...";
    rows[15] = "....CCCTTCCC....";
  }
  if ((a.activite === "snack" || a.activite === "cafe") && a.etat === "debout" && Math.floor(t / 30) % 2)
    rows[14] = "..SSCCCTTCCC...."; // porte à la bouche
  if (a.parle && a.etat === "debout" && Math.floor(t / 10) % 2) rows[15] = "..SSCCCTTCCCS...";
  if (acc === "lunettes") { rows[6] = ".SGWEGSSSSGWEGS."; rows[7] = ".SGEEGGGGGGEEGS."; rows[8] = ".SGEEGSSSSGEEGS."; }
  if (acc === "chapeau") {
    rows[0] = "...RRRRRRRRRR..."; rows[1] = "...RRRRRRRRRR..."; rows[2] = "...YYYYYYYYYY..."; rows[3] = "RRRRRRRRRRRRRRRR";
    pal.R = a.id === "pelosi" ? "#2a2a3a" : "#8a4a22"; pal.Y = a.id === "pelosi" ? "#c0303a" : "#2a1a10";
  }
  if (acc === "casquette") {
    rows[0] = "....RRRRRRRR...."; rows[1] = "..RRRRRRRRRRRR.."; rows[2] = ".RRRRRRRRRRRRRR."; rows[3] = ".YYYYYYYYYYYYYY.";
    pal.R = a.id === "risk" ? "#ffcc4d" : "#2a6ad8"; pal.Y = a.id === "risk" ? "#c8961a" : "#1a4aa0";
  }
  const dort = a.activite === "sieste" && a.etat === "pouf";
  if (dort || Math.floor((t + a.anim * 40) / 180) % 18 === 0) for (const r of [6, 8]) rows[r] = rows[r].replace(/[EW]/g, "S"); // yeux fermés
  if (!dort && Math.floor((t + a.anim * 40) / 180) % 18 === 0) rows[7] = rows[7].replace(/[EW]/g, "S");
  if (a.dos) rows = rows.map((r, i) => i <= 11 ? r.replace(/[SEWKG]/g, "H") : r.replace(/T/g, "C")); // vu de dos
  return { rows, pal };
}
function dessinerPerso(a, t) {
  const { rows, pal } = sprite(a, t);
  const rebond = a.activite === "fete" && a.etat === "debout" ? -2 * (Math.floor(t / 10) % 2)
    : a.activite === "musique" ? Math.floor(t / 12) % 2
    : a.activite === "sieste" ? Math.floor(t / 60) % 2
    : a.travail ? Math.floor(t / 20) % 2
    : a.etat === "assis" ? Math.floor((t + a.anim * 30) / 40) % 2 : 0;
  const n = assise(a) ? ASSIS_Y + 1 : a.etat === "canape" ? 14 : rows.length;
  const x0 = Math.round(a.x), y0 = Math.round(a.y) + rebond;
  if (a.etat === "marche" || a.etat === "debout") { ctx.fillStyle = "#00000055"; ctx.fillRect(x0 + 2, y0 + PH - 1, 12, 2); ctx.fillRect(x0 + 4, y0 + PH + 1, 8, 1); }
  ctx.fillStyle = "#0b0814"; // contour sombre façon figurine
  for (let r = 0; r < n; r++) for (let c = 0; c < PW; c++) {
    if (rows[r][c] === ".") continue;
    ctx.fillRect(x0 + c - 1, y0 + r, 3, 1); ctx.fillRect(x0 + c, y0 + r - 1, 1, 3);
  }
  for (let r = 0; r < n; r++) for (let c = 0; c < PW; c++) {
    const k = rows[r][c]; if (k === ".") continue;
    ctx.fillStyle = pal[k]; ctx.fillRect(x0 + c, y0 + r, 1, 1);
  }
  if (!a.dos) { ctx.fillStyle = "#ffffff30"; ctx.fillRect(x0 + 3, y0 + 1, 4, 1); ctx.fillRect(x0 + 2, y0 + 2, 1, 2); } // reflet vinyle
  if (a.activite === "musique") {
    ctx.fillStyle = "#222"; ctx.fillRect(x0 + 2, y0 - 1, 12, 1); ctx.fillRect(x0 + 1, y0, 1, 5); ctx.fillRect(x0 + 14, y0, 1, 5);
    ctx.fillStyle = "#e0404a"; ctx.fillRect(x0 - 1, y0 + 5, 2, 4); ctx.fillRect(x0 + 15, y0 + 5, 2, 4);
  }
  if (a.activite === "fete") {
    const raies = ["#ff5d9e", "#ffcc4d"];
    [[7, 1], [7, 2], [6, 3], [6, 4], [5, 5], [5, 6]].forEach(([dx, w], i) => { ctx.fillStyle = raies[i % 2]; ctx.fillRect(x0 + dx, y0 - 7 + i, w, 1); });
    ctx.fillStyle = "#fff"; ctx.fillRect(x0 + 7, y0 - 8, 2, 1);
  }
  if ((a.activite === "snack" || a.activite === "cafe") && a.etat === "debout" && Math.floor(t / 30) % 2) {
    ctx.fillStyle = a.activite === "cafe" ? "#e8e4ff" : a.place === "soda" ? "#3a8ad8" : "#c0703a";
    ctx.fillRect(x0 + 2, y0 + 11, 3, 3);
  }
  if (a.statut && !a.activite) { ctx.fillStyle = a.statut === "ok" ? "#5be37d" : "#ff5d6c"; ctx.fillRect(x0 + 6, y0 - 5, 4, 3); }
}

// ---------- Mobilier ----------
function dessinerBureau(a, t) {
  const s = a.bureau, dir = a.id === "directeur";
  const x = dir ? 54 : s.bx, y = s.haut, w = dir ? 60 : 26;
  ctx.fillStyle = "#00000040"; ctx.fillRect(x + 1, y + 11, w, 2); // ombre au sol
  ctx.fillStyle = dir ? "#6a3a20" : "#7a5230"; ctx.fillRect(x, y, w, 8);
  ctx.fillStyle = dir ? "#8a5030" : "#9a6a40"; ctx.fillRect(x, y, w, 2);
  ctx.fillStyle = dir ? "#b07848" : "#c08a58"; ctx.fillRect(x, y, w, 1); // arête éclairée
  ctx.fillStyle = "#00000030"; ctx.fillRect(x, y + 7, w, 1);
  ctx.fillStyle = "#4a2e1a"; ctx.fillRect(x + 1, y + 8, 2, 3); ctx.fillRect(x + w - 3, y + 8, 2, 3);
  ctx.fillStyle = dir ? "#4a2a14" : "#6a4426"; ctx.fillRect(x + 3, y + 4, 6, 1); // tiroir
  if (dir) { ctx.fillStyle = "#ffcc4d"; ctx.fillRect(x + 26, y + 3, 8, 3); ctx.fillStyle = "#1a1420"; ctx.fillRect(x + 27, y + 4, 6, 1); }
  // papiers : une pile et une feuille
  const px = dir ? 58 : s.bx + 1;
  ctx.fillStyle = "#d8d4e8"; ctx.fillRect(px, y - 3, 6, 3); ctx.fillStyle = "#fffbe8"; ctx.fillRect(px, y - 4, 6, 1);
  ctx.fillStyle = "#9a93c4"; ctx.fillRect(px + 1, y - 2, 4, 1);
  ctx.fillStyle = "#fffbe8"; ctx.fillRect(px + 7, y - 1, 5, 1);
  // écran
  const mx = dir ? 98 : s.bx + 17, my = y - 8;
  ctx.fillStyle = "#2a2838"; ctx.fillRect(mx, my, 9, 7); ctx.fillRect(mx + 3, my + 7, 3, 1);
  ctx.fillStyle = a.travail ? "#0d2a1a" : "#141a2a"; ctx.fillRect(mx + 1, my + 1, 7, 5);
  if (a.travail) {
    ctx.fillStyle = "#5be37d";
    for (let i = 0; i < 7; i++) ctx.fillRect(mx + 1 + i, my + 2 + Math.floor((Math.sin((t / 8) + i * 0.9 + a.anim) + 1) * 1.5), 1, 1);
  } else if (a.statut) {
    ctx.fillStyle = a.statut === "ok" ? "#5be37d" : "#ff5d6c"; ctx.fillRect(mx + 2, my + 2, 5, 2);
  } else { ctx.fillStyle = "#2a3a5a"; ctx.fillRect(mx + 2, my + 2, 3, 1); ctx.fillRect(mx + 2, my + 4, 2, 1); }
  ctx.fillStyle = "#3a3848"; ctx.fillRect(mx - 9, y - 1, 7, 1); // clavier
  ctx.fillStyle = "#e8e4ff"; ctx.fillRect(dir ? 70 : s.bx + 13, y - 3, 2, 2); // tasse
}
function chaise(s) { // dossier de fauteuil derrière l'agent (visible quand il est parti)
  const [x, y] = s.siege;
  ctx.fillStyle = "#0b0814"; ctx.fillRect(x + 2, y + 7, 12, 12);
  ctx.fillStyle = "#2a2840"; ctx.fillRect(x + 3, y + 8, 10, 10);
  ctx.fillStyle = "#3e3a5c"; ctx.fillRect(x + 4, y + 9, 8, 2);
}
function classeur(x, y) {
  ctx.fillStyle = "#6a6f80"; ctx.fillRect(x, y, 9, 24);
  ctx.fillStyle = "#8a90a4"; ctx.fillRect(x, y, 9, 1);
  for (let i = 0; i < 3; i++) {
    ctx.fillStyle = "#565a6a"; ctx.fillRect(x + 1, y + 2 + i * 7, 7, 6);
    ctx.fillStyle = "#c8ccd8"; ctx.fillRect(x + 3, y + 4 + i * 7, 3, 1);
    ctx.fillStyle = "#fffbe8"; ctx.fillRect(x + 2, y + 2 + i * 7, 5, 1); // dossiers qui dépassent
  }
  ctx.fillStyle = "#d84a4a"; ctx.fillRect(x + 1, y - 3, 3, 3); ctx.fillStyle = "#4a8ad8"; ctx.fillRect(x + 4, y - 4, 3, 4); // classeurs posés dessus
}
function plante(x, y) {
  ctx.fillStyle = "#8a4a2a"; ctx.fillRect(x, y + 10, 8, 7);
  ctx.fillStyle = "#3aa85a"; ctx.fillRect(x + 1, y + 2, 6, 8); ctx.fillRect(x - 1, y + 5, 10, 3);
  ctx.fillStyle = "#5be37d"; ctx.fillRect(x + 3, y, 2, 4);
}
function distributeur(x, y, corps, vitre, articles, t) {
  ctx.fillStyle = corps; ctx.fillRect(x, y, 15, 28);
  ctx.fillStyle = "#0e0c1a"; ctx.fillRect(x + 2, y + 3, 8, 17);
  for (let r = 0; r < 4; r++) for (let c = 0; c < 3; c++) { ctx.fillStyle = articles[(r + c) % articles.length]; ctx.fillRect(x + 3 + c * 2, y + 4 + r * 4, 1, 2); }
  ctx.fillStyle = vitre; ctx.fillRect(x + 2, y + 3, 8, 1);
  ctx.fillStyle = Math.floor(t / 30) % 2 ? "#5be37d" : "#2a6a3a"; ctx.fillRect(x + 11, y + 5, 2, 2);
  ctx.fillStyle = "#c8ccd8"; ctx.fillRect(x + 11, y + 9, 2, 6);
  ctx.fillStyle = "#1a1420"; ctx.fillRect(x + 2, y + 22, 8, 3);
}
function mobilierDetente(t) {
  return [
    { base: 222, f: () => distributeur(170, 194, "#d8603a", "#ffd0a0", ["#c0703a", "#ffcc4d", "#e04a4a"], t) },
    { base: 222, f: () => distributeur(186, 194, "#2a6ad8", "#a0d0ff", ["#3a8ad8", "#e04a4a", "#5be37d"], t) },
    { base: 222, f: () => { // comptoir café
      ctx.fillStyle = "#7a5230"; ctx.fillRect(202, 210, 13, 12); ctx.fillStyle = "#9a6a40"; ctx.fillRect(202, 210, 13, 2);
      ctx.fillStyle = "#2a2838"; ctx.fillRect(204, 200, 9, 10); ctx.fillStyle = "#c0303a"; ctx.fillRect(205, 202, 7, 3);
      if (Math.floor(t / 20) % 3) { ctx.fillStyle = "#ffffff66"; ctx.fillRect(208, 197 - (t / 10) % 3, 1, 2); }
    } },
    { base: 258, f: () => { // canapé vu de dos
      ctx.fillStyle = "#b0445a"; ctx.fillRect(226, 242, 74, 12);
      ctx.fillStyle = "#c85a70"; ctx.fillRect(226, 242, 74, 2);
      ctx.fillStyle = "#8a3446"; ctx.fillRect(224, 240, 4, 18); ctx.fillRect(298, 240, 4, 18); ctx.fillRect(226, 254, 74, 4);
      ctx.fillStyle = "#9a3c50"; ctx.fillRect(250, 244, 1, 9); ctx.fillRect(275, 244, 1, 9);
    } },
    { base: 252, f: () => { // pouf
      ctx.fillStyle = "#e0a030"; ctx.fillRect(306, 238, 22, 13); ctx.fillStyle = "#f0c050"; ctx.fillRect(308, 238, 18, 3);
    } },
    { base: 262, f: () => plante(320, 244) },
    { base: 262, f: () => plante(378, 244) },
    { base: 262, f: () => plante(378, 198) },
    { base: 262, f: () => plante(172, 244) },
  ];
}

// ---------- Décor (sols, murs, couloirs) ----------
function damier(x, y, w, h, c1, c2, k = 8) {
  for (let j = y; j < y + h; j += k) for (let i = x; i < x + w; i += k) {
    ctx.fillStyle = ((i - x) / k + (j - y) / k) % 2 ? c1 : c2; ctx.fillRect(i, j, Math.min(k, x + w - i), Math.min(k, y + h - j));
  }
}
function parquet(x, y, w, h, c) {
  const clair = shade(c, 1.1), fonce = shade(c, 0.94), joint = shade(c, 0.78);
  for (let j = 0, r = 0; j < h; j += 5, r++) {
    ctx.fillStyle = r % 2 ? clair : fonce; ctx.fillRect(x, y + j, w, Math.min(5, h - j));
    ctx.fillStyle = joint; ctx.fillRect(x, y + j, w, 1);
    for (let i = (r * 13) % 24; i < w; i += 24) ctx.fillRect(x + i, y + j, 1, Math.min(5, h - j));
  }
}
function piece(s, sol1, sol2, mur) {
  if (sol2) damier(s.x0, s.y0, s.w, s.h, sol1, sol2); else parquet(s.x0, s.y0, s.w, s.h, sol1);
  ctx.fillStyle = mur; ctx.fillRect(s.x0, s.y0, s.w, 14);            // mur du fond
  ctx.fillStyle = shade(mur, 0.78); ctx.fillRect(s.x0, s.y0 + 8, s.w, 6); // boiserie
  ctx.fillStyle = shade(mur, 1.3); ctx.fillRect(s.x0, s.y0 + 8, s.w, 1);
  ctx.fillStyle = "#00000055"; ctx.fillRect(s.x0, s.y0 + 13, s.w, 1); ctx.fillStyle = "#00000022"; ctx.fillRect(s.x0, s.y0 + 14, s.w, 2); // plinthe et ombre
  const g = s.type === "detente" ? [s.dedans[0] - 2, 22] : [s.allee + 1, 18];  // ouverture de la porte
  ctx.fillStyle = "#1d1830";
  ctx.fillRect(s.x0, s.y0, 2, s.h); ctx.fillRect(s.x0 + s.w - 2, s.y0, 2, s.h);
  const haut = s.porte === "haut", yb = s.y0 + s.h - 2;
  // mur du haut et du bas, avec un trou pour la porte
  for (const [yy, trou] of [[s.y0, haut], [yb, !haut]]) {
    if (!trou) { ctx.fillRect(s.x0, yy, s.w, 2); continue; }
    ctx.fillRect(s.x0, yy, g[0] - s.x0, 2); ctx.fillRect(g[0] + g[1], yy, s.x0 + s.w - g[0] - g[1], 2);
  }
  if (haut) { ctx.fillStyle = "#4b4566"; ctx.fillRect(g[0], s.y0, g[1], 14); ctx.fillStyle = "#1d1830"; }  // embrasure dans le mur du fond
  ctx.fillStyle = "#8a5a30"; // battant ouvert
  if (haut) ctx.fillRect(g[0] + g[1], s.y0 + 2, 2, 12); else ctx.fillRect(g[0] + g[1], yb - 12, 2, 12);
}
function fenetre(x, y, nuit) {
  ctx.fillStyle = "#e8e4ff"; ctx.fillRect(x, y, 16, 12);
  ctx.fillStyle = nuit ? "#121838" : "#7ac0ff"; ctx.fillRect(x + 1, y + 1, 14, 10);
  ctx.fillStyle = nuit ? "#1a2050" : "#a8d8ff"; ctx.fillRect(x + 1, y + 1, 14, 3);
  for (const [ix, iy, iw] of [[1, 6, 4], [6, 4, 4], [11, 7, 4]]) {
    ctx.fillStyle = nuit ? "#232a4a" : "#4a5a80"; ctx.fillRect(x + ix, y + iy, iw, 11 - iy);
    ctx.fillStyle = nuit ? "#ffd86a" : "#c8e4ff"; for (let wy = iy + 1; wy < 10; wy += 2) ctx.fillRect(x + ix + 1, y + wy, 1, 1);
  }
  ctx.fillStyle = "#e8e4ff"; ctx.fillRect(x + 8, y + 1, 1, 10);
  ctx.fillStyle = "#ffffff38"; for (let i = 0; i < 5; i++) ctx.fillRect(x + 2 + i, y + 6 - i, 1, 1); // reflet
}
let chaine = 0;
function tele(t) {
  const x = 246, y = 194, on = Object.values(agents).some(a => a.activite === "tele" && a.etat === "canape");
  ctx.fillStyle = "#111"; ctx.fillRect(x, y, 46, 22); ctx.fillStyle = "#333"; ctx.fillRect(x + 20, y + 22, 6, 2);
  if (!on) { ctx.fillStyle = "#0a0a12"; ctx.fillRect(x + 2, y + 2, 42, 18); ctx.fillStyle = "#c0303a"; ctx.fillRect(x + 42, y + 19, 1, 1); return; }
  chaine = Math.floor(t / 540) % 3;
  if (chaine === 0) { // foot
    ctx.fillStyle = "#2a8a3a"; ctx.fillRect(x + 2, y + 2, 42, 18);
    ctx.fillStyle = "#e8ffe8"; ctx.fillRect(x + 22, y + 2, 1, 18); ctx.fillRect(x + 2, y + 10, 3, 3); ctx.fillRect(x + 41, y + 10, 3, 3);
    const bx = x + 22 + Math.round(Math.sin(t / 25) * 16), by = y + 11 + Math.round(Math.cos(t / 17) * 6);
    ctx.fillStyle = "#fff"; ctx.fillRect(bx, by, 2, 2);
    ctx.fillStyle = "#e04a4a"; ctx.fillRect(bx - 4, by + 2, 2, 3); ctx.fillStyle = "#3a6ad8"; ctx.fillRect(bx + 5, by - 3, 2, 3);
  } else if (chaine === 1) { // bourse
    ctx.fillStyle = "#0d1a3a"; ctx.fillRect(x + 2, y + 2, 42, 18); ctx.fillStyle = "#5be37d";
    for (let i = 0; i < 40; i++) ctx.fillRect(x + 3 + i, y + 11 + Math.round(Math.sin(i / 4 + t / 40) * 4 - i / 10), 1, 1);
    ctx.fillStyle = "#ffcc4d"; ctx.fillRect(x + 2, y + 17, 42, 3);
  } else { // dessin animé
    ctx.fillStyle = "#7ac0ff"; ctx.fillRect(x + 2, y + 2, 42, 18); ctx.fillStyle = "#5be37d"; ctx.fillRect(x + 2, y + 16, 42, 4);
    const cx = x + 8 + (Math.floor(t / 2) % 30), cy = y + 10 - Math.abs(Math.round(Math.sin(t / 10) * 5));
    ctx.fillStyle = "#ffcc4d"; ctx.fillRect(cx, cy, 5, 5); ctx.fillStyle = "#120c18"; ctx.fillRect(cx + 1, cy + 1, 1, 1); ctx.fillRect(cx + 3, cy + 1, 1, 1);
  }
}
function decor(t) {
  ctx.fillStyle = "#120f1d"; ctx.fillRect(0, 0, W, H);
  damier(0, 74, W, 22, "#4b4566", "#46405f"); damier(336, 96, 56, 74, "#4b4566", "#46405f"); damier(0, 170, W, 22, "#4b4566", "#46405f");
  for (const [x, y, w, h] of [[4, 79, W - 8, 12], [4, 175, W - 8, 12], [LIAISON + 3, 91, 12, 84]]) { // tapis des couloirs
    ctx.fillStyle = "#6a2a3a"; ctx.fillRect(x, y, w, h); ctx.fillStyle = "#c8963a"; ctx.fillRect(x + 1, y + 1, w - 2, h - 2);
    ctx.fillStyle = "#7a3444"; ctx.fillRect(x + 2, y + 2, w - 4, h - 4);
  }
  const h = new Date().getHours(), nuit = h < 7 || h >= 20;
  EQUIPES.forEach((e, i) => {
    piece(e, e.sol, null, ["#5a4f7a", "#4f6a6a", "#6a4f6a"][i]);
    const postes = e.membres.map(id => SALLES[id]);
    [postes[0], postes[postes.length - 1]].forEach(p => fenetre(p.bx + 6, e.y0 + 1, nuit));
    plante(e.x0 + e.w - 13, e.y0 + (e.porte === "bas" ? 50 : 52));
  });
  // équipe Plan : tableau blanc
  ctx.fillStyle = "#c8ccd8"; ctx.fillRect(368, 2, 21, 13); ctx.fillStyle = "#fbfbff"; ctx.fillRect(369, 3, 19, 10);
  ctx.fillStyle = "#3a6ad8"; ctx.fillRect(371, 5, 6, 1); ctx.fillRect(371, 8, 4, 1);
  ctx.fillStyle = "#e04a4a"; for (let i = 0; i < 8; i++) ctx.fillRect(378 + i, 11 - Math.round(i / 2), 1, 1);
  // équipe Exécution : écran mural + table de réunion
  ctx.fillStyle = "#0b0814"; ctx.fillRect(184, 97, 64, 13); ctx.fillStyle = "#0d1a3a"; ctx.fillRect(185, 98, 62, 11); ctx.fillStyle = "#5be37d";
  for (let i = 0; i < 58; i++) ctx.fillRect(187 + i, 103 + Math.round(Math.sin(i / 5 + t / 50) * 3 - i / 30), 1, 1);
  ctx.fillStyle = "#00000040"; ctx.fillRect(186, 136, 62, 3);
  ctx.fillStyle = "#4a2e1a"; ctx.fillRect(184, 122, 62, 14); ctx.fillStyle = "#7a5230"; ctx.fillRect(184, 122, 62, 12);
  ctx.fillStyle = "#9a6a40"; ctx.fillRect(184, 122, 62, 2); ctx.fillStyle = "#c08a58"; ctx.fillRect(184, 122, 62, 1);
  for (const cx of [190, 204, 218, 232]) {
    ctx.fillStyle = "#2a2840"; ctx.fillRect(cx, 117, 8, 5); ctx.fillRect(cx, 137, 8, 4);
    ctx.fillStyle = "#fffbe8"; ctx.fillRect(cx + 1, 126, 5, 3);
  }
  // bureau du Directeur
  const d = SALLES.directeur;
  piece(d, "#5a3a2a", null, "#6a5a8a");
  ctx.fillStyle = "#6a2a3a"; ctx.fillRect(44, 212, 84, 44); ctx.fillStyle = "#c8963a"; ctx.fillRect(45, 213, 82, 42);
  ctx.fillStyle = "#8a3a4a"; ctx.fillRect(47, 215, 78, 38); ctx.fillStyle = "#9a4a5a"; ctx.fillRect(50, 218, 72, 32);
  ctx.fillStyle = "#1a1530"; ctx.fillRect(28, 193, 44, 12); ctx.fillStyle = nuit ? "#121838" : "#7ac0ff"; ctx.fillRect(29, 194, 42, 10);
  [[30, 198, 6], [37, 196, 7], [45, 199, 5], [51, 195, 8], [60, 197, 6], [66, 199, 4]].forEach(([ix, iy, iw]) => {
    ctx.fillStyle = nuit ? "#232a4a" : "#4a5a80"; ctx.fillRect(ix, iy, iw, 204 - iy);
    ctx.fillStyle = nuit ? "#ffd86a" : "#c8e4ff"; for (let wy = iy + 1; wy < 203; wy += 2) ctx.fillRect(ix + 1, wy, 1, 1);
  });
  ctx.fillStyle = "#0a0a12"; ctx.fillRect(76, 194, 72, 11); ctx.fillStyle = "#4d4590"; ctx.fillRect(76, 194, 72, 1); ctx.fillRect(76, 204, 72, 1);
  const now = new Date(), hx = 157, hy = 199;
  ctx.fillStyle = "#e8e4ff"; ctx.fillRect(hx - 6, hy - 6, 12, 12); ctx.fillStyle = "#2a2444"; ctx.fillRect(hx - 5, hy - 5, 10, 10);
  ctx.fillStyle = "#e8e4ff"; ctx.fillRect(hx - 4, hy - 4, 8, 8);
  const aig = (ang, len, col) => { ctx.fillStyle = col; for (let i = 0; i < len; i++) ctx.fillRect(Math.round(hx + Math.sin(ang) * i), Math.round(hy - Math.cos(ang) * i), 1, 1); };
  aig((now.getHours() % 12 + now.getMinutes() / 60) / 12 * 2 * Math.PI, 3, "#1a1020");
  aig(now.getMinutes() / 60 * 2 * Math.PI, 4, "#1a1020");
  aig(now.getSeconds() / 60 * 2 * Math.PI, 4, "#c0303a");
  plante(4, 244); plante(150, 244);
  // coin détente
  piece(DETENTE, "#8a6a4a", null, "#6a8a7a");
  ctx.fillStyle = "#4a7a6a"; ctx.fillRect(226, 212, 76, 26); ctx.fillStyle = "#5a8a7a"; ctx.fillRect(228, 214, 72, 22); // tapis
  tele(t);
  ctx.fillStyle = "#ffcc4d"; ctx.fillRect(300, 196, 10, 8); ctx.fillStyle = "#ff5d9e"; ctx.fillRect(312, 197, 8, 9); // affiches
  if (performance.now() < finFete) {
    const disco = ["#ff5d9e66", "#59c3ff66", "#ffcc4d66", "#5be37d66"];
    PISTE.forEach(([x, y], i) => { ctx.fillStyle = disco[(i + Math.floor(t / 15)) % 4]; ctx.fillRect(x - 2, y + 18, 20, 6); });
  }
}

// ---------- Déplacements (par les portes et les couloirs) ----------
function ouEst(a) {
  const fx = a.x + 8, fy = a.y + 20;
  const s = LISTE_SALLES.find(s => fx >= s.x0 && fx < s.x0 + s.w && fy >= s.y0 && fy < s.y0 + s.h);
  if (s) return s;
  const c = fy < 133 ? 1 : 2;
  return { couloir: c, dehors: [a.x, c === 1 ? C1 : C2], dansCouloir: true };
}
function sortir(s, a) {
  if (s.dansCouloir) return [];
  return s.type === "detente" ? [[a.x, s.rang], [s.dedans[0], s.rang], s.dedans] : [[s.allee, a.y], s.dedans];
}
function entrer(s, tx, ty) {
  return s.type === "detente" ? [s.dedans, [s.dedans[0], s.rang], [tx, s.rang], [tx, ty]] : [s.dedans, [s.allee, ty], [tx, ty]];
}
function trajet(a, s, tx, ty) {
  s = s.salle || s; // un poste d'équipe → sa salle
  const ici = ouEst(a); let p;
  if (ici === s) p = s.type === "detente" ? [[a.x, s.rang], [tx, s.rang], [tx, ty]] : [[s.allee, a.y], [s.allee, ty], [tx, ty]];
  else {
    p = [...sortir(ici, a), ici.dehors];
    if (ici.couloir !== s.couloir) p.push([LIAISON, ici.dehors[1]], [LIAISON, s.dehors[1]]);
    p.push(s.dehors, ...entrer(s, tx, ty));
  }
  a.dos = false; a.chemin = p; a.etat = "marche";
  return new Promise(res => (a.arrive = () => { a.etat = "debout"; res(); }));
}
function rentrer(a) {
  if (a.etat === "assis" && !a.chemin.length) return Promise.resolve();
  return trajet(a, a.bureau, ...a.bureau.siege).then(() => { a.etat = "assis"; });
}
const visiter = (a, cible) => trajet(a, cible.bureau, ...cible.bureau.visite);
function bouger(a) {
  if (!a.chemin.length) return;
  const [tx, ty] = a.chemin[0];
  const dx = tx - a.x, dy = ty - a.y, d = Math.hypot(dx, dy);
  if (d <= a.vitesse) {
    a.x = tx; a.y = ty; a.chemin.shift();
    if (!a.chemin.length) { a.etat = "debout"; const f = a.arrive; a.arrive = null; f && f(); }
  } else { a.x += dx / d * a.vitesse; a.y += dy / d * a.vitesse; a.pas++; }
}

// ---------- Effets ----------
const papiers = [], particules = [];
function envoyerPapier(de, vers) { papiers.push({ x0: de.cx, y0: de.haut - 6, x1: vers.cx, y1: vers.haut - 4, k: 0 }); }
function effets() {
  for (let i = papiers.length - 1; i >= 0; i--) {
    const p = papiers[i]; p.k += 0.015;
    const x = p.x0 + (p.x1 - p.x0) * p.k, y = p.y0 + (p.y1 - p.y0) * p.k - Math.sin(p.k * Math.PI) * 24;
    ctx.fillStyle = "#fffbe8"; ctx.fillRect(Math.round(x) - 2, Math.round(y) - 3, 5, 6);
    ctx.fillStyle = "#9a93c4"; ctx.fillRect(Math.round(x) - 1, Math.round(y) - 1, 3, 1); ctx.fillRect(Math.round(x) - 1, Math.round(y) + 1, 3, 1);
    if (p.k >= 1) papiers.splice(i, 1);
  }
  const NOTES = ["#ff5d9e", "#59c3ff", "#ffcc4d", "#5be37d"];
  for (const a of Object.values(agents)) {
    if (a.travail && Math.random() < 0.08)
      particules.push({ x: a.cx + 5 + Math.random() * 7, y: a.haut - 9, vx: 0, vy: -0.3 - Math.random() * 0.3, vie: 40, c: Math.random() < 0.7 ? "#5be37d" : "#ffcc4d" });
    if (a.activite === "musique" && Math.random() < 0.035)
      particules.push({ forme: "note", x: a.x + (Math.random() < 0.5 ? -2 : 15), y: a.y + 4, vx: (Math.random() - 0.5) * 0.3, vy: -0.35, vie: 55, c: NOTES[Math.floor(Math.random() * 4)] });
    if (a.activite === "fete" && a.etat === "debout" && Math.random() < 0.25)
      particules.push({ x: a.x + Math.random() * 16, y: a.y - 12, vx: (Math.random() - 0.5) * 0.6, vy: 0.4 + Math.random() * 0.4, vie: 60, c: NOTES[Math.floor(Math.random() * 4)] });
    if (a.activite === "sieste" && a.etat === "pouf" && Math.random() < 0.02)
      particules.push({ forme: "z", x: a.x + 12, y: a.y - 2, vx: 0.15, vy: -0.25, vie: 60, c: "#cfc8ff" });
  }
  for (let i = particules.length - 1; i >= 0; i--) {
    const p = particules[i]; p.x += p.vx; p.y += p.vy; p.vie--;
    ctx.fillStyle = p.c;
    const x = Math.round(p.x), y = Math.round(p.y);
    if (p.forme === "note") { ctx.fillRect(x + 2, y, 1, 3); ctx.fillRect(x + 2, y, 2, 1); ctx.fillRect(x, y + 2, 2, 2); }
    else if (p.forme === "z") { ctx.fillRect(x, y, 3, 1); ctx.fillRect(x + 1, y + 1, 1, 1); ctx.fillRect(x, y + 2, 3, 1); }
    else ctx.fillRect(x, y, 1, 2);
    if (p.vie <= 0) particules.splice(i, 1);
  }
}

// ---------- Bulles et étiquettes HTML ----------
const etiquettes = {};
for (const a of Object.values(agents)) {
  const e = document.createElement("div"); e.className = "nom"; calque.appendChild(e); etiquettes[a.id] = e;
}
const etiquetteDetente = document.createElement("div"); etiquetteDetente.className = "nom"; etiquetteDetente.textContent = "COIN DÉTENTE"; calque.appendChild(etiquetteDetente);
const plaques = EQUIPES.map(e => {
  const p = document.createElement("div"); p.className = "nom equipe"; p.textContent = e.nom.replace("ÉQUIPE ", ""); calque.appendChild(p);
  const postes = e.membres.map(id => SALLES[id]);
  return { p, x: (postes[0].bx + postes[postes.length - 1].bx) / 2 + 14, y: e.y0 + 3 }; // entre les deux fenêtres
});
const tableau = document.createElement("div"); tableau.className = "tableau";
tableau.innerHTML = "<span>BIENVENUE AU BUREAU DES TRADERS · LANCE UNE MISSION À DROITE</span>"; calque.appendChild(tableau);
const bulles = [];
function dire(a, texte, genre = "", duree = 4500) {
  bulles.filter(b => Math.hypot(b.a.x - a.x, b.a.y - a.y) < 40).forEach(b => b.fin = 0); // une seule bulle par coin
  const e = document.createElement("div"); e.className = "bulle " + genre; e.textContent = texte; calque.appendChild(e);
  bulles.push({ a, e, fin: performance.now() + duree });
}
function placerHTML(now) {
  for (const a of Object.values(agents)) {
    const e = etiquettes[a.id], [ex, ey] = a.bureau.etiquette; e.textContent = a.nom.toUpperCase();
    Object.assign(e.style, { left: ex * S + "px", top: ey * S + "px", fontSize: S * 2.2 + "px" });
  }
  for (const q of plaques) Object.assign(q.p.style, { left: q.x * S + "px", top: q.y * S + "px", fontSize: S * 2 + "px" });
  Object.assign(etiquetteDetente.style, { left: 196 * S + "px", top: 260 * S + "px", fontSize: S * 2.2 + "px" });
  Object.assign(tableau.style, { left: 77 * S + "px", top: 195 * S + "px", width: 70 * S + "px", height: 9 * S + "px", fontSize: S * 2.2 + "px" });
  for (let i = bulles.length - 1; i >= 0; i--) {
    const b = bulles[i];
    if (now > b.fin) { b.e.style.opacity = 0; if (now > b.fin + 400) { b.e.remove(); bulles.splice(i, 1); } continue; }
    b.e.style.fontSize = S * 3.6 + "px"; b.e.style.maxWidth = S * 64 + "px";
    const bx = Math.min(Math.max((b.a.x + PW / 2) * S, S * 34), W * S - S * 34);
    b.e.style.left = bx + "px"; b.e.style.top = Math.max((b.a.y - 3) * S, S * 16) + "px";
  }
}
function majTableau(lignes) {
  if (!lignes.length) return;
  tableau.innerHTML = ""; const s = document.createElement("span");
  s.textContent = lignes.slice(-6).join("   ·   "); tableau.appendChild(s);
}

// ---------- Lumière : plafonniers chauds, lueur des écrans, vignette ----------
const LAMPES = [[120, 30, 90], [316, 30, 70], [110, 126, 90], [250, 126, 70], [84, 226, 70], [280, 226, 90]];
function lumiere() {
  ctx.save(); ctx.globalCompositeOperation = "lighter";
  const halo = (x, y, r, c) => {
    const g = ctx.createRadialGradient(x, y, 0, x, y, r); g.addColorStop(0, c); g.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = g; ctx.fillRect(x - r, y - r, 2 * r, 2 * r);
  };
  LAMPES.forEach(([x, y, r]) => halo(x, y, r, "rgba(255,200,130,0.13)"));
  for (const a of Object.values(agents)) if (a.travail) halo(a.id === "directeur" ? 102 : a.bureau.bx + 21, a.haut - 5, 16, "rgba(90,255,140,0.28)");
  if (performance.now() < finFete) halo(260, 225, 60, `hsla(${(t * 4) % 360},90%,60%,0.18)`);
  ctx.restore();
  const v = ctx.createRadialGradient(W / 2, H / 2, 110, W / 2, H / 2, 230);
  v.addColorStop(0, "rgba(8,5,20,0)"); v.addColorStop(1, "rgba(8,5,20,0.55)");
  ctx.fillStyle = v; ctx.fillRect(0, 0, W, H);
}

// ---------- Boucle ----------
let t = 0;
const baseDe = a => a.etat === "assis" ? a.haut + 8 : a.etat === "canape" ? 241 : a.etat === "pouf" ? 251 : a.y + PH;
function boucle(now) {
  t++;
  ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.clearRect(0, 0, cv.width, cv.height);
  ctx.setTransform(S, 0, 0, S, 0, 0); ctx.imageSmoothingEnabled = false;
  decor(t);
  const objets = mobilierDetente(t);
  for (const a of Object.values(agents)) {
    bouger(a);
    const s = a.bureau;
    objets.push({ base: a.haut + 9, f: () => dessinerBureau(a, t) });
    if (a.id === "directeur") { objets.push({ base: 230, f: () => { classeur(140, 206); classeur(152, 206); } }); }
    else objets.push({ base: s.y0 + 34, f: () => classeur(s.bx + 28, s.y0 + 10) });
    objets.push({ base: a.haut + 7, f: () => chaise(s) });
    objets.push({ base: baseDe(a), f: () => dessinerPerso(a, t) });
  }
  objets.sort((p, q) => p.base - q.base).forEach(o => o.f());
  lumiere();
  effets();
  placerHTML(now);
  requestAnimationFrame(boucle);
}
function redimensionner() {
  const zone = document.getElementById("scene");
  const fit = Math.max(0.5, Math.min((zone.clientWidth - 32) / W, (zone.clientHeight - 32) / H));
  S = Math.max(1, Math.ceil(fit)); // dessin net en entier, puis mise à l'échelle CSS pour remplir
  cv.width = W * S; cv.height = H * S;
  cadre.style.transform = `scale(${fit / S})`;
  cadre.style.margin = `${(H * fit - H * S) / 2}px ${(W * fit - W * S) / 2}px`; // la transformation ne change pas la place occupée
}
addEventListener("resize", redimensionner); redimensionner(); requestAnimationFrame(boucle);

// ---------- Vie de bureau : personne n'est jamais AFK ----------
let enMission = false;
const hasard = l => l[Math.floor(Math.random() * l.length)];
const DIALOGUES = [
  ["Tu as vu TSLA ce matin ?", "Oui, ça bouge dans tous les sens !", "Le Guetteur attend la cassure.", "Comme toujours, patience…"],
  ["On mange quoi ce midi ?", "Sushis, comme d'hab'.", "Encore ? Ok, vendu !"],
  ["Le Gardien a encore tout bloqué…", "Il fait son travail, heureusement !", "Pas de stop, pas de trade."],
  ["Tu crois au robotaxi ?", "Moi je crois au stop-loss.", "Haha, sage réponse."],
  ["10 000 replays, rien que ça ?", "Le Voyageur ne dort jamais.", "Il rejoue même ses rêves."],
  ["T'as écouté le nouveau son ?", "En boucle depuis hier !", "Tu me fais la playlist ?"],
  ["La cloche sonne à quelle heure ?", "9 h 30 à New York.", "Donc 15 h 30 chez nous."],
  ["Je me suis fait sortir au stop…", "C'est le jeu, ça protège le capital.", "Le prochain sera le bon !"],
  ["Pelosi a encore acheté du Nvidia ?", "L'Espion épluche les déclarations.", "Il a 45 jours pour déclarer, hein."],
  ["Tu fais quoi ce week-end ?", "Je relis des 10-Q. Et toi ?", "Pareil… on est des passionnés."],
  ["Il reste des chips au distributeur ?", "Plus que les goûts bizarres.", "Tant pis, je prends quand même."],
  ["Qui a mis le foot sur la télé ?", "C'est l'Espion, il espionne le score.", "Haha !"],
];
const TRAVAIL = {
  directeur: ["Je répartis le travail…", "Qui est libre ?"],
  scanner: ["Je passe 5 928 graphiques…", "Bougie après bougie…"],
  news: ["Je lis les dépêches…", "Un 8-K vient de tomber ?"],
  entry: ["J'attends la clôture de la bougie…", "Ça casse ou pas ?"],
  exit: ["Je calcule le stop…", "Objectif à 2R…"],
  timemachine: ["Replay 7 342 / 10 000…", "Je remonte le temps…"],
  budget: ["Je compte les actions…", "Combien on peut risquer ?"],
  risk: ["Je vérifie les règles…", "Rien ne passe sans moi."],
  broker: ["Je remplis le ticket…", "Papier, pas réel !"],
  alerts: ["Je surveille l'horloge…", "Tic tac…"],
  analyst: ["Je lis le 10-Q…", "Marge en hausse ?"],
  pelosi: ["J'épluche les déclarations…", "Qui a acheté quoi ?"],
  fouineuse: ["Je fouille Yahoo Finance…", "Qui monte le plus ?", "Volume x5, tiens tiens…"],
  crieur: ["Ça parle de NVDA partout !", "Je lis StockTwits…", "Reddit s'enflamme…"],
};
const TELE = [
  ["BUUUT !", "Hors-jeu, arbitre !", "Quelle frappe !", "Allez allez !"],
  ["Le Nasdaq repart !", "Tiens, ils parlent de TSLA.", "Encore la Fed…", "Je l'avais dit !"],
  ["Haha, trop drôle !", "Mon dessin animé préféré !", "Il saute partout !"],
];
let finFete = 0;

function libre(a) { return a.etat === "assis" && !a.chemin.length && !a.travail && !a.activite && (a.id !== "directeur" || !enMission); }
function arreter(a) { a.activite = null; a.parle = false; a.place = null; a.jeton = (a.jeton || 0) + 1; }
const placeLibre = noms => noms.find(n => !Object.values(agents).some(b => b.place === n));
// Lance une activité : f reçoit un test « toujours d'actualité ? » et libère l'agent à la fin.
async function activite(a, nom, f) {
  arreter(a); a.activite = nom; const j = a.jeton, ok = () => a.jeton === j;
  try { await f(ok); } finally { if (ok()) { if (a.etat !== "assis") await rentrer(a); if (ok()) arreter(a); } }
}
const musique = a => activite(a, "musique", async () => {
  if (Math.random() < 0.5) dire(a, hasard(["♪ Ma playlist de trading", "Ce son est trop bien !", "♫ ♫ ♫", "Un peu de jazz…"]), "", 2500);
  await pause(7000 + Math.random() * 8000);
});
function aLaDetente(a, nom, places, phrases, duree, poser) {
  const p = placeLibre(places); if (!p) return musique(a);
  return activite(a, nom, async ok => {
    a.place = p; await trajet(a, DETENTE, ...PLACES[p]); if (!ok()) return;
    if (poser) poser(a);
    const fin = performance.now() + duree;
    dire(a, hasard(phrases()), "", 2600);
    while (ok() && performance.now() < fin) {
      await pause(3500);
      if (ok() && Math.random() < 0.35) dire(a, hasard(phrases()), "", 2600);
    }
  });
}
const snack = a => aLaDetente(a, "snack", ["snack", "soda"], () => a.place === "soda"
  ? ["Un soda bien frais 🥤", "De l'eau, c'est plus sain.", "Glou glou…"]
  : ["Une barre chocolatée 🍫", "Des chips !", "Miam, un cookie."], 5000 + Math.random() * 3000);
const cafe = a => aLaDetente(a, "cafe", ["cafe"], () => ["Un café ☕", "Double espresso !", "Qui a fini le lait ?", "Pause méritée."], 5000 + Math.random() * 3000);
const regarderTele = a => aLaDetente(a, "tele", ["canape0", "canape1", "canape2"], () => TELE[chaine], 12000 + Math.random() * 10000,
  b => { b.etat = "canape"; b.dos = true; });
const sieste = a => aLaDetente(a, "sieste", ["pouf"], () => ["Petite pause… 😴", "Zzz…", "Je ferme les yeux 5 minutes."], 10000 + Math.random() * 6000,
  b => { b.etat = "pouf"; });
function discussion(a, b) {
  const lignes = hasard(DIALOGUES);
  activite(b, "discussion", async okB => {
    await activite(a, "discussion", async okA => {
      await trajet(a, b.bureau, ...b.bureau.visite2);
      for (let i = 0; i < lignes.length && okA() && okB(); i++) {
        const qui = i % 2 ? b : a; qui.parle = true;
        dire(qui, lignes[i], "", 2800); await pause(3000); qui.parle = false;
      }
    });
  });
}
function fete(groupe) {
  finFete = performance.now() + 18000;
  groupe.forEach((a, i) => activite(a, "fete", async ok => {
    await trajet(a, DETENTE, ...PISTE[i]); if (!ok()) return;
    dire(a, hasard(["C'est la fête ! 🎉", "Wouhou !", "On a battu le marché !", "Le DJ, c'est moi !", "Allez, on danse !"]), "", 2500);
    while (ok() && performance.now() < finFete) await pause(500);
  }));
}
setInterval(() => {
  for (const a of Object.values(agents)) {
    if (a.travail && Math.random() < 0.15) dire(a, hasard(TRAVAIL[a.id]), "", 2500);
    // filet de sécurité : debout sans rien faire → retour au bureau (le Directeur reste en tournée pendant une mission)
    if (!a.activite && !a.travail && a.etat !== "assis" && !a.chemin.length && !(a.id === "directeur" && enMission)) rentrer(a);
  }
  const libres = Object.values(agents).filter(libre);
  if (!enMission && performance.now() > finFete + 40000 && libres.length >= 6 && Math.random() < 0.05)
    return fete(libres.sort(() => Math.random() - 0.5).slice(0, 3 + Math.floor(Math.random() * 3)));
  if (Math.random() < 0.35) return;
  const a = hasard(libres); if (!a) return;
  const r = Math.random(), autres = libres.filter(b => b !== a);
  if (r < 0.28 && autres.length) discussion(a, hasard(autres));
  else if (r < 0.45) musique(a);
  else if (r < 0.65) regarderTele(a);
  else if (r < 0.8) snack(a);
  else if (r < 0.9) cafe(a);
  else sieste(a);
}, 2500);
// Une mission arrive : tout le monde arrête sa pause et retourne à son bureau.
function rappeler() {
  finFete = 0;
  for (const a of Object.values(agents)) if (a.activite) { arreter(a); if (a.etat !== "assis") rentrer(a); }
}

// ---------- File du directeur ----------
const dir = agents.directeur;
let file = Promise.resolve();
const faire = f => (file = file.then(f).catch(console.error));
const pause = ms => new Promise(r => setTimeout(r, ms));

// ---------- Journal ----------
const NOMS = {};
const journal = document.getElementById("journal");
function noter(html, cls = "") {
  const d = document.createElement("div"); d.className = cls; d.innerHTML = html; journal.appendChild(d);
  while (journal.children.length > 400) journal.firstChild.remove();
  journal.scrollTop = journal.scrollHeight;
}
const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const couleur = id => LOOK[id] ? LOOK[id][2] : "#fff";
const tag = id => `<b style="color:${id === "directeur" ? "#ffcc4d" : couleur(id)}">[${esc(NOMS[id] || id)}]</b>`;

// ---------- Mises à jour au lancement ----------
let majEtat = "verif", majAffiche = 0, majCible = 0, majPas = 100;
const dMaj = document.getElementById("d-maj"), majBarre = document.getElementById("maj-barre");
dMaj.addEventListener("cancel", e => e.preventDefault()); // Échap ne contourne pas la question
(function portrait() {
  const cv = document.getElementById("maj-portrait"), c = cv.getContext("2d");
  const { rows, pal } = sprite({ ...dir, dos: false, activite: null, etat: "debout", anim: 0 }, 200); // t=200 : yeux ouverts
  rows.slice(0, cv.height).forEach((r, y) => [...r].forEach((k, x) => { if (k !== ".") { c.fillStyle = pal[k]; c.fillRect(x, y, 1, 1); } }));
})();
setInterval(() => { // la barre avance doucement pendant une étape, sans jamais dépasser la suivante
  if (majEtat !== "maj") return;
  majAffiche = Math.max(majAffiche, majCible);
  if (majAffiche < majCible + majPas * 0.9) majAffiche += majPas / 60;
  barre(majAffiche);
}, 300);
function barre(p) {
  p = Math.min(100, Math.round(p));
  majBarre.firstElementChild.style.width = p + "%"; majBarre.setAttribute("aria-valuenow", p);
}
function majUI(m) {
  if (!m) return;
  const avant = majEtat; majEtat = m.etat;
  const texte = document.getElementById("maj-texte"), liste = document.getElementById("maj-liste");
  document.getElementById("maj-choix").hidden = m.etat !== "propose";
  majBarre.hidden = !["maj", "pret"].includes(m.etat) || avant === "verif";
  if (m.etat === "verif") {
    texte.textContent = "Un instant, je vérifie les mises à jour avant d'ouvrir le bureau…"; liste.replaceChildren();
  } else if (m.etat === "propose") {
    texte.textContent = "J'ai trouvé des mises à jour. On les installe avant de commencer ?";
    liste.replaceChildren(...m.liste.map(n => Object.assign(document.createElement("li"), { textContent: n })));
    majPas = 100 / Math.max(1, m.liste.length);
  } else if (m.etat === "maj") {
    texte.textContent = m.texte || "Mise à jour en cours…"; liste.replaceChildren(); majCible = m.pct;
  }
  if (m.etat !== "pret") { if (!dMaj.open) dMaj.showModal(); occupe(enMission); return; }
  if (avant === "pret") return;
  const ouvrir = () => {
    if (dMaj.open) dMaj.close();
    occupe(enMission);
    const msg = avant === "verif" ? "Tout est à jour. Au travail, l'équipe !" : `${m.texte || "C'est prêt."} Au travail, l'équipe !`;
    noter(`${tag("directeur")} ${esc(msg)}`, m.texte && /échoué/.test(m.texte) ? "ko" : "ok");
    dire(dir, msg, "dir", 5000);
  };
  if (avant === "maj") { texte.textContent = m.texte; barre(100); setTimeout(ouvrir, 1500); } else ouvrir();
}
async function repondreMaj(oui) {
  document.getElementById("maj-choix").hidden = true;
  if (oui) { majEtat = "maj"; majAffiche = majCible = 0; barre(0); majBarre.hidden = false; }
  await fetch("/api/maj", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ oui }) }).catch(() => {});
}
document.getElementById("maj-oui").onclick = () => repondreMaj(true);
document.getElementById("maj-non").onclick = () => repondreMaj(false);

// ---------- Événements du serveur ----------
const statut = document.getElementById("statut");
const boutons = [...document.querySelectorAll("button[data-m]")];
function occupe(oui) {
  enMission = oui; boutons.forEach(b => (b.disabled = oui || majEtat !== "pret"));
  statut.textContent = oui ? "● mission en cours" : "● prêt"; statut.classList.toggle("occupe", oui);
}
const tickerLignes = [];
function traiter(ev, anime = true) {
  const a = agents[ev.agent];
  if (ev.type === "mission") {
    if (ev.status === "start") {
      occupe(true); noter(`${tag("directeur")} Nouvelle mission : ${esc(ev.name)}${ev.symbol ? " " + esc(ev.symbol) : ""}`, "dir");
      Object.values(agents).forEach(x => (x.statut = null));
      if (anime) rappeler();
      if (anime) faire(async () => { dire(dir, "Au travail, l'équipe !", "dir", 2500); await pause(1200); });
    } else {
      occupe(false);
      if (anime) faire(async () => {
        await rentrer(dir); dir.etat = "assis";
        dire(dir, ev.ok ? "Mission terminée. Beau travail !" : "Mission arrêtée, on verra plus tard.", ev.ok ? "ok" : "ko", 5000);
      });
      noter(`${tag("directeur")} ${ev.ok ? "Mission terminée." : "Mission arrêtée."}`, ev.ok ? "ok" : "ko");
    }
  } else if (ev.type === "order") {
    noter(`${tag("directeur")} → ${tag(ev.agent)} ${esc(ev.text)}`, "dir");
    if (anime) faire(async () => {
      await visiter(dir, a); dire(dir, ev.text, "dir", 3500); await pause(1300);
      dire(a, "Compris, chef !", "", 2000); await pause(700);
    });
  } else if (ev.type === "step") {
    if (ev.status === "start") {
      a.sortie = [`$ ${ev.cmd}`];
      if (anime) {
        if (a.activite) arreter(a);
        rentrer(a).then(() => { a.etat = "assis"; }); a.travail = true; a.statut = null;
        setTimeout(() => a.travail && dire(a, hasard(TRAVAIL[a.id]), "", 2500), 2600);
      }
    } else {
      a.travail = false; a.statut = ev.status === "done" ? "ok" : "ko";
      noter(`${tag(ev.agent)} ${ev.status === "done" ? "✓" : "✗"} ${esc(ev.summary)}`, ev.status === "done" ? "ok" : "ko");
      if (anime) { dire(a, ev.summary, ev.status === "done" ? "ok" : "ko", 6500); envoyerPapier(a, dir); }
    }
  } else if (ev.type === "line") {
    a.sortie.push(ev.text); if (a.sortie.length > 500) a.sortie.shift();
    noter(esc(ev.text), "brut");
    if (/\$\d|RSI|breakout|cassure|PASS|BLOCK|triggered/i.test(ev.text)) { tickerLignes.push(ev.text.trim()); majTableau(tickerLignes); }
  } else if (ev.type === "maj") {
    majUI(ev);
  } else if (ev.type === "serveur") {
    noter(`<b style="color:#8a8f98">[serveur]</b> ${esc(ev.text)}`, /error|traceback|exception/i.test(ev.text) ? "ko" : "brut");
  } else if (ev.type === "say") {
    noter(`${tag("directeur")} ${esc(ev.text)}`, "dir");
    if (anime) faire(async () => { dire(dir, ev.text, "dir", 5000); await pause(800); });
  }
}

fetch("/api/state").then(r => r.json()).then(st => {
  Object.assign(NOMS, st.agents);
  for (const [id, nom] of Object.entries(st.agents)) agents[id].nom = nom;
  st.history.forEach(ev => traiter(ev, false));
  majUI(st.maj);
  occupe(st.busy);
  remplirReglages(st.config);
  noter(`${tag("directeur")} Bonjour ! Choisis une mission, je répartis le travail.`, "dir");
  dire(dir, "Bonjour ! Choisis une mission →", "dir", 6000);
  const es = new EventSource("/api/events" + (new URLSearchParams(location.search).has("app") ? "?app=1" : ""));
  es.onmessage = m => traiter(JSON.parse(m.data));
  // la vérification a pu finir entre /api/state et la connexion : on relit l'état
  es.onopen = () => fetch("/api/state").then(r => r.json()).then(s => majUI(s.maj)).catch(() => {});
  es.onerror = () => { statut.textContent = "● serveur coupé"; statut.classList.add("occupe"); };
});

// ---------- Boutons ----------
boutons.forEach(b => b.addEventListener("click", async () => {
  const symbol = document.getElementById("ticker").value.trim().toUpperCase();
  if (b.dataset.m === "action" && !symbol) { document.getElementById("ticker").focus(); dire(dir, "Quel ticker ? (ex. TSLA)", "dir"); return; }
  const r = await fetch("/api/mission", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: b.dataset.m, symbol }) });
  const j = await r.json(); if (j.error) { dire(dir, j.error, "ko"); noter(esc(j.error), "ko"); }
}));

// clic sur un agent : sa dernière sortie
cv.addEventListener("click", e => {
  const rect = cv.getBoundingClientRect(), x = (e.clientX - rect.left) / rect.width * W, y = (e.clientY - rect.top) / rect.height * H;
  const a = Object.values(agents).find(a => x > a.x - 1 && x < a.x + PW + 1 && y > a.y - 1 && y < a.y + PH + 1) ||
            Object.values(agents).find(a => Math.abs(x - a.cx) < 16 && y > a.haut - 16 && y < a.haut + 11);
  if (!a) return;
  document.getElementById("d-titre").textContent = (NOMS[a.id] || a.id).toUpperCase();
  document.getElementById("d-role").textContent = ROLES[a.id];
  document.getElementById("d-sortie").textContent = a.sortie.length ? a.sortie.join("\n") : "Pas encore de travail dans cette session.";
  document.getElementById("d-agent").showModal();
});

// ---------- Réglages ----------
const dReg = document.getElementById("d-reglages"), fReg = document.getElementById("f-reglages");
function remplirReglages(cfg) { for (const [k, v] of Object.entries(cfg || {})) if (fReg.elements[k]) fReg.elements[k].value = v ?? ""; }
document.getElementById("btn-reglages").onclick = () => dReg.showModal();
document.getElementById("annuler").onclick = () => dReg.close();
fReg.addEventListener("submit", async e => {
  e.preventDefault();
  const data = Object.fromEntries(new FormData(fReg));
  const r = await fetch("/api/config", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });
  const j = await r.json();
  if (j.error) { alert(j.error); return; }
  dReg.close(); dire(agents.budget, "Réglages notés !", "ok"); noter(`${tag("budget")} Réglages enregistrés.`, "ok");
});
