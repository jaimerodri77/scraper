<?php

// URL raw de tu repositorio GitHub
define('GITHUB_RAW', 'https://raw.githubusercontent.com/TU_USUARIO/TU_REPO/main/datos/');

function leerJSON(string $archivo): array {
    $url  = GITHUB_RAW . $archivo;
    $json = @file_get_contents($url);
    return $json ? json_decode($json, true) : [];
}

$partidos = leerJSON('partidos.json');
$atp      = leerJSON('rankings_atp.json');
$wta      = leerJSON('rankings_wta.json');
?>
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <title>🎾 Estadísticas de Tenis</title>
    <style>
        body { font-family: Arial, sans-serif; max-width: 1000px; margin: auto; padding: 20px; }
        table { width: 100%; border-collapse: collapse; margin-bottom: 30px; }
        th { background: #2c7a2c; color: white; padding: 10px; }
        td { padding: 8px; border-bottom: 1px solid #ddd; }
        tr:hover { background: #f5f5f5; }
        h2 { color: #2c7a2c; border-bottom: 2px solid #2c7a2c; padding-bottom: 5px; }
        .badge { padding: 3px 8px; border-radius: 10px; font-size: 12px; }
        .finalizado { background: #d4edda; color: #155724; }
        .en-juego   { background: #fff3cd; color: #856404; }
        .por-jugar  { background: #cce5ff; color: #004085; }
    </style>
</head>
<body>

<h1>🎾 Estadísticas de Tenis</h1>
<p>Última actualización: <strong><?= $partidos['fecha'] ?? 'N/A' ?></strong></p>

<!-- Partidos -->
<h2>📅 Partidos del Día</h2>
<table>
    <tr><th>Torneo</th><th>Jugador 1</th><th>Score</th><th>Jugador 2</th><th>Estado</th></tr>
    <?php foreach (($partidos['partidos'] ?? []) as $p): ?>
    <tr>
        <td><?= htmlspecialchars($p['torneo'] ?? '-') ?></td>
        <td><?= htmlspecialchars($p['jugador1'] ?? '-') ?></td>
        <td style="text-align:center;font-weight:bold">
            <?= htmlspecialchars(($p['score1'] ?? '0') . ' - ' . ($p['score2'] ?? '0')) ?>
        </td>
        <td><?= htmlspecialchars($p['jugador2'] ?? '-') ?></td>
        <td>
            <span class="badge <?= strtolower(str_replace(' ', '-', $p['estado'] ?? '')) ?>">
                <?= htmlspecialchars($p['estado'] ?? '-') ?>
            </span>
        </td>
    </tr>
    <?php endforeach; ?>
</table>

<!-- Ranking ATP -->
<h2>🏆 Ranking ATP (Top 20)</h2>
<table>
    <tr><th>#</th><th>Jugador</th><th>País</th><th>Puntos</th></tr>
    <?php foreach (array_slice($atp['jugadores'] ?? [], 0, 20) as $j): ?>
    <tr>
        <td><?= htmlspecialchars($j['posicion']) ?></td>
        <td><?= htmlspecialchars($j['nombre']) ?></td>
        <td><?= htmlspecialchars($j['pais']) ?></td>
        <td><?= number_format((int)$j['puntos']) ?></td>
    </tr>
    <?php endforeach; ?>
</table>

<!-- Ranking WTA -->
<h2>🏆 Ranking WTA (Top 20)</h2>
<table>
    <tr><th>#</th><th>Jugadora</th><th>País</th><th>Puntos</th></tr>
    <?php foreach (array_slice($wta['jugadores'] ?? [], 0, 20) as $j): ?>
    <tr>
        <td><?= htmlspecialchars($j['posicion']) ?></td>
        <td><?= htmlspecialchars($j['nombre']) ?></td>
        <td><?= htmlspecialchars($j['pais']) ?></td>
        <td><?= number_format((int)$j['puntos']) ?></td>
    </tr>
    <?php endforeach; ?>
</table>

</body>
</html>
