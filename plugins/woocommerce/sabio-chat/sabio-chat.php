<?php
/**
 * Plugin Name:       SABIO Chat
 * Description:       Agrega el asistente SABIO al pie de tu sitio. Responde solo con la información publicada en tu tienda.
 * Version:           1.0.0
 * Requires at least: 5.8
 * Requires PHP:      7.4
 * Author:            Equipo SABIO (USAL)
 * License:           GPLv2 or later
 * License URI:       https://www.gnu.org/licenses/gpl-2.0.html
 * Text Domain:       sabio-chat
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

define( 'SABIO_CHAT_OPTION', 'sabio_chat_settings' );

/** Ajustes guardados, con valores vacíos por defecto. */
function sabio_chat_settings() {
	return wp_parse_args(
		get_option( SABIO_CHAT_OPTION, array() ),
		array(
			'server'  => '',
			'site_id' => '',
		)
	);
}

/** Limpia lo que se carga en la página de ajustes. */
function sabio_chat_sanitize( $input ) {
	$input   = is_array( $input ) ? $input : array();
	$server  = isset( $input['server'] ) ? esc_url_raw( trim( $input['server'] ), array( 'https', 'http' ) ) : '';
	$site_id = isset( $input['site_id'] ) ? preg_replace( '/[^A-Za-z0-9_-]/', '', $input['site_id'] ) : '';
	return array(
		'server'  => untrailingslashit( $server ),
		'site_id' => $site_id,
	);
}

add_action(
	'admin_init',
	function () {
		register_setting( 'sabio_chat', SABIO_CHAT_OPTION, array( 'sanitize_callback' => 'sabio_chat_sanitize' ) );
	}
);

add_action(
	'admin_menu',
	function () {
		add_options_page( 'SABIO Chat', 'SABIO Chat', 'manage_options', 'sabio-chat', 'sabio_chat_settings_page' );
	}
);

/** Página Ajustes › SABIO Chat. */
function sabio_chat_settings_page() {
	if ( ! current_user_can( 'manage_options' ) ) {
		return;
	}
	$s = sabio_chat_settings();
	?>
	<div class="wrap">
		<h1>SABIO Chat</h1>
		<p>Copiá estos datos del panel de SABIO (<code>/admin</code>), en la línea de instalación de tu sitio.</p>
		<form method="post" action="options.php">
			<?php settings_fields( 'sabio_chat' ); ?>
			<table class="form-table" role="presentation">
				<tr>
					<th scope="row"><label for="sabio-server">URL del servidor</label></th>
					<td>
						<input type="url" id="sabio-server" class="regular-text" placeholder="https://sabio-ppsl.onrender.com"
							name="<?php echo esc_attr( SABIO_CHAT_OPTION ); ?>[server]"
							value="<?php echo esc_attr( $s['server'] ); ?>">
						<p class="description">La dirección del servidor SABIO, sin la barra final.</p>
					</td>
				</tr>
				<tr>
					<th scope="row"><label for="sabio-site">ID del sitio</label></th>
					<td>
						<input type="text" id="sabio-site" class="regular-text" placeholder="s_1a2b3c4d5e"
							name="<?php echo esc_attr( SABIO_CHAT_OPTION ); ?>[site_id]"
							value="<?php echo esc_attr( $s['site_id'] ); ?>">
						<p class="description">El valor de <code>data-site</code> en la línea de instalación.</p>
					</td>
				</tr>
			</table>
			<?php submit_button(); ?>
		</form>
	</div>
	<?php
}

/** Inserta el widget en el pie de todas las páginas públicas, solo si está configurado. */
add_action(
	'wp_footer',
	function () {
		$s = sabio_chat_settings();
		if ( empty( $s['server'] ) || empty( $s['site_id'] ) ) {
			return;
		}
		printf(
			'<script src="%s" data-site="%s" defer></script>' . "\n",
			esc_url( $s['server'] . '/widget.js' ),
			esc_attr( $s['site_id'] )
		);
	}
);

/** Enlace "Ajustes" en la lista de plugins. */
add_filter(
	'plugin_action_links_' . plugin_basename( __FILE__ ),
	function ( $links ) {
		array_unshift( $links, '<a href="' . esc_url( admin_url( 'options-general.php?page=sabio-chat' ) ) . '">Ajustes</a>' );
		return $links;
	}
);
