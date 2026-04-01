from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file, abort, jsonify
from io import BytesIO
import pyodbc
import pandas as pd
import io
from dotenv import load_dotenv
import json
import os
import datetime
from flask import send_from_directory
import unicodedata
import re
import time
import logging
from functools import wraps

# Seguridad
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Importar configuraciones y consultas
from config import Config
from auth_decorator import login_required
from logging_config import setup_logging
from queries import (
    INGRESOS_DETALLADOS, EGRESOS_DETALLADOS, STOCK_DETALLADO, STOCK_CANTIDAD,
    INGRESOS_POR_MES, INGRESOS_POR_RANGO, EGRESOS_POR_MES, EGRESOS_POR_RANGO,
    MOVIMIENTOS_SERIADOS_POR_MES, MOVIMIENTOS_SERIADOS_POR_RANGO,
    TRACKING_POR_SERIAL, ROTACION_EGRESOS, ROTACION_INGRESOS
)

# Cargar variables de entorno
load_dotenv()

app = Flask(__name__)
app.config.from_object(Config)
app.secret_key = Config.SECRET_KEY
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# Configurar logging
access_logger = setup_logging()
logger = logging.getLogger(__name__)

# Configurar rate limiting
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"
)


# ============================================
# FUNCIONES AUXILIARES
# ============================================

def normalizar_usuario(usuario):
    """Normaliza el nombre de usuario: quita acentos, mayúsculas y reemplaza espacios"""
    if not usuario:
        return usuario
    usuario = usuario.upper().strip()
    usuario = unicodedata.normalize('NFKD', usuario)
    usuario = usuario.encode('ascii', 'ignore').decode('ascii')
    usuario = re.sub(r'[\.\s\-]+', '_', usuario)
    return usuario


def ejecutar_consulta(query, params=None):
    """
    Ejecuta consultas SQL de forma segura usando parámetros
    Previene inyección SQL
    """
    try:
        with pyodbc.connect(Config.CONN_STR, timeout=30) as conn:
            if params:
                if not isinstance(params, (list, tuple)):
                    params = [params]
                df = pd.read_sql(query, conn, params=params)
            else:
                df = pd.read_sql(query, conn)
        return df
    except pyodbc.Error as e:
        logger.error(f"Error en base de datos: {str(e)}")
        raise Exception("Error al consultar la base de datos")
    except Exception as e:
        logger.error(f"Error inesperado: {str(e)}")
        raise


def exportar_a_excel(df, nombre_archivo):
    """Exporta DataFrame a Excel de forma segura"""
    try:
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Datos')
        output.seek(0)

        # Sanitizar nombre de archivo
        nombre_archivo = re.sub(r'[^\w\-_\. ]', '', nombre_archivo)

        return send_file(
            output,
            as_attachment=True,
            download_name=nombre_archivo,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    except Exception as e:
        logger.error(f"Error exportando Excel: {str(e)}")
        abort(500)


def log_acceso(usuario, intento_exitoso=True):
    """Registra intentos de acceso"""
    ip = request.remote_addr
    user_agent = request.headers.get('User-Agent', 'Desconocido')
    estado = "EXITOSO" if intento_exitoso else "FALLIDO"
    access_logger.info(f"{estado} - Usuario: {usuario} - IP: {ip} - UA: {user_agent}")


def sanitizar_entrada(valor):
    """Sanitiza entrada de usuario para prevenir XSS"""
    if valor is None:
        return ""
    if isinstance(valor, str):
        valor = re.sub(r'[<>"\']', '', valor)
        return valor.strip()
    return valor


# ============================================
# RUTAS PÚBLICAS
# ============================================

@app.route('/', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
def login():
    if request.method == 'POST':
        usuario = sanitizar_entrada(request.form.get('usuario', ''))
        contrasena = request.form.get('contrasena', '')

        if not usuario or not contrasena:
            return render_template('login.html', error='Complete todos los campos')

        try:
            with open('usuarios.json', 'r', encoding='utf-8') as file:
                usuarios = json.load(file)

            usuario_normalizado = normalizar_usuario(usuario)
            usuario_encontrado = None

            # Buscar usuario
            for usuario_key in usuarios.keys():
                if normalizar_usuario(usuario_key) == usuario_normalizado:
                    usuario_encontrado = usuario_key
                    break

            # Verificar con HASH
            if usuario_encontrado and check_password_hash(usuarios[usuario_encontrado], contrasena):
                session.clear()
                session['usuario'] = usuario_encontrado
                session['cliente'] = usuario_encontrado
                session['login_time'] = datetime.datetime.now().isoformat()
                log_acceso(usuario_encontrado, intento_exitoso=True)

                flash('Bienvenido al sistema', 'success')
                return redirect(url_for('dashboard'))
            else:
                time.sleep(1)
                log_acceso(usuario, intento_exitoso=False)
                return render_template('login.html', error='Credenciales inválidas')

        except FileNotFoundError:
            logger.error("Archivo usuarios.json no encontrado")
            return render_template('login.html', error='Error interno del servidor')
        except Exception as e:
            logger.error(f"Error en login: {str(e)}")
            return render_template('login.html', error='Error interno del servidor')

    return render_template('login.html')


# ============================================
# RUTAS PROTEGIDAS
# ============================================

@app.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html")


@app.route('/consulta/<tipo>')
@login_required
def consulta(tipo):
    usuario = session.get('usuario')

    consultas = {
        'ingresos': {'query': INGRESOS_DETALLADOS, 'titulo': 'Ingresos Detallados'},
        'egresos': {'query': EGRESOS_DETALLADOS, 'titulo': 'Egresos Detallados'},
        'stock_detallado': {'query': STOCK_DETALLADO, 'titulo': 'Stock Detallado'},
        'stock_cantidad': {'query': STOCK_CANTIDAD, 'titulo': 'Stock en Cantidad'}
    }

    if tipo not in consultas:
        flash('Tipo de consulta no válido', 'error')
        return redirect(url_for('dashboard'))

    try:
        consulta_info = consultas[tipo]
        df = ejecutar_consulta(consulta_info['query'], [usuario])

        if request.args.get('exportar') == 'excel':
            return exportar_a_excel(df, f'{tipo}.xlsx')

        return render_template(
            'table.html',
            titulo=consulta_info['titulo'],
            columnas=df.columns.tolist(),
            datos=df.values.tolist()
        )
    except Exception as e:
        logger.error(f"Error en consulta {tipo}: {str(e)}")
        flash('Error al obtener los datos', 'error')
        return redirect(url_for('dashboard'))


@app.route('/seleccionar_anio/<tipo>', methods=['GET', 'POST'])
@login_required
def seleccionar_anio(tipo):
    if tipo not in ['ingresos', 'egresos']:
        flash('Tipo no válido', 'error')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        anio = sanitizar_entrada(request.form.get('anio', ''))
        mes = sanitizar_entrada(request.form.get('mes', ''))
        desde = sanitizar_entrada(request.form.get('desde', ''))
        hasta = sanitizar_entrada(request.form.get('hasta', ''))

        if anio and mes:
            return redirect(url_for('seleccionar_anio', tipo=tipo, anio=anio, mes=mes))
        elif desde and hasta:
            return redirect(url_for('seleccionar_anio', tipo=tipo, desde=desde, hasta=hasta))
        else:
            flash('Elegí una de las dos opciones: año/mes o rango de fechas.', 'warning')
            return redirect(request.url)

    anio = request.args.get('anio')
    mes = request.args.get('mes')
    desde = request.args.get('desde')
    hasta = request.args.get('hasta')
    exportar = request.args.get('exportar')

    if not ((anio and mes) or (desde and hasta)):
        return render_template('filtro_fecha.html', tipo=tipo)

    usuario = session.get('usuario')

    try:
        if tipo == 'ingresos':
            if anio and mes:
                query = INGRESOS_POR_MES
                params = [usuario, anio, mes]
                titulo = f'Ingresos Detallados - {mes}/{anio}'
            else:
                query = INGRESOS_POR_RANGO
                params = [usuario, desde, hasta]
                titulo = f'Ingresos Detallados - {desde} a {hasta}'
        else:
            if anio and mes:
                query = EGRESOS_POR_MES
                params = [usuario, anio, mes]
                titulo = f'Egresos Detallados - {mes}/{anio}'
            else:
                query = EGRESOS_POR_RANGO
                params = [usuario, desde, hasta]
                titulo = f'Egresos Detallados - {desde} a {hasta}'

        df = ejecutar_consulta(query, params)

        if exportar == 'excel':
            nombre = f"{tipo}_{mes}_{anio}.xlsx" if anio and mes else f"{tipo}_{desde}_a_{hasta}.xlsx"
            return exportar_a_excel(df, nombre)

        return render_template(
            'table.html',
            titulo=titulo,
            columnas=df.columns.tolist(),
            datos=df.values.tolist()
        )

    except Exception as e:
        logger.error(f"Error en seleccionar_anio {tipo}: {str(e)}")
        flash('Error al obtener los datos', 'error')
        return redirect(url_for('dashboard'))


@app.route('/ingresos_seriados', methods=['GET', 'POST'])
@login_required
def ingresos_seriados():
    return procesar_movimientos_seriados('Ingresos')


@app.route('/egresos_seriados', methods=['GET', 'POST'])
@login_required
def egresos_seriados():
    return procesar_movimientos_seriados('Egresos')


def procesar_movimientos_seriados(tipo_operacion):
    usuario = session.get('usuario')

    if request.method == 'POST':
        anio = sanitizar_entrada(request.form.get('anio', ''))
        mes = sanitizar_entrada(request.form.get('mes', ''))
        desde = sanitizar_entrada(request.form.get('desde', ''))
        hasta = sanitizar_entrada(request.form.get('hasta', ''))

        if anio and mes:
            return redirect(url_for(f'{tipo_operacion.lower()}_seriados', anio=anio, mes=mes))
        elif desde and hasta:
            return redirect(url_for(f'{tipo_operacion.lower()}_seriados', desde=desde, hasta=hasta))
        else:
            return render_template('filtro_fecha.html', tipo=f'{tipo_operacion.lower()}_seriados',
                                   error='Elegí una de las dos opciones.')

    anio = request.args.get('anio')
    mes = request.args.get('mes')
    desde = request.args.get('desde')
    hasta = request.args.get('hasta')
    exportar = request.args.get('exportar')

    if not ((anio and mes) or (desde and hasta)):
        return render_template('filtro_fecha.html', tipo=f'{tipo_operacion.lower()}_seriados')

    try:
        if anio and mes:
            query = MOVIMIENTOS_SERIADOS_POR_MES
            params = [usuario, tipo_operacion, anio, mes]
            titulo = f'{tipo_operacion} Seriados - {mes}/{anio}'
        else:
            query = MOVIMIENTOS_SERIADOS_POR_RANGO
            params = [usuario, tipo_operacion, desde, hasta]
            titulo = f'{tipo_operacion} Seriados - {desde} a {hasta}'

        df = ejecutar_consulta(query, params)

        if exportar == 'excel':
            nombre = f'{tipo_operacion.lower()}_{mes}_{anio}.xlsx' if anio and mes else f'{tipo_operacion.lower()}_{desde}_a_{hasta}.xlsx'
            return exportar_a_excel(df, nombre)

        return render_template(
            'table.html',
            titulo=titulo,
            columnas=df.columns.tolist(),
            datos=df.values.tolist()
        )

    except Exception as e:
        logger.error(f"Error en {tipo_operacion} seriados: {str(e)}")
        flash('Error al obtener los datos', 'error')
        return redirect(url_for('dashboard'))


@app.route("/consulta/rotacion", methods=["GET", "POST"])
@login_required
def consulta_rotacion():
    if request.method == "POST":
        try:
            fecha_inicio = sanitizar_entrada(request.form.get("fecha_inicio", ""))
            fecha_fin = sanitizar_entrada(request.form.get("fecha_fin", ""))

            if not fecha_inicio or not fecha_fin:
                flash('Debe completar ambas fechas', 'warning')
                return redirect(url_for('consulta_rotacion'))

            output = exportar_rotacion_excel(fecha_inicio, fecha_fin)
            return send_file(
                output,
                as_attachment=True,
                download_name="rotacion_inventario.xlsx",
                mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        except Exception as e:
            logger.error(f"Error en rotación: {str(e)}")
            flash('Error al generar el reporte', 'error')
            return redirect(url_for('consulta_rotacion'))

    return render_template("rotacion.html")


def exportar_rotacion_excel(fecha_inicio, fecha_fin):
    usuario = session.get("usuario")

    df = ejecutar_consulta(ROTACION_EGRESOS, [usuario, fecha_inicio, fecha_fin])
    df_ingresos = ejecutar_consulta(ROTACION_INGRESOS, [usuario])

    df_ingresos.rename(columns={'FECHA_COMPROBANTE': 'FECHA_INGRESO'}, inplace=True)
    df_ingresos = df_ingresos.drop_duplicates(subset=['NRO_SERIE'], keep='first')

    df = df.merge(df_ingresos[['NRO_SERIE', 'FECHA_INGRESO']], on='NRO_SERIE', how='left')
    df['ANTIGÜEDAD'] = (pd.to_datetime(df['F_OPERACION']) -
                        pd.to_datetime(df['FECHA_INGRESO'], errors='coerce')).dt.days

    def clasificar_periodicidad(dias):
        if pd.isna(dias):
            return "Sin Fecha de Ingreso", "gray"
        elif dias <= 30:
            return "0-30 días", "green"
        elif dias <= 60:
            return "31-60 días", "yellow"
        elif dias <= 90:
            return "61-90 días", "orange"
        elif dias <= 120:
            return "91-120 días", "lightcoral"
        elif dias <= 180:
            return "121-180 días", "red"
        elif dias <= 365:
            return "181-365 días", "blue"
        else:
            return "Más de 365 días", "gray"

    df[['PERIODICIDAD', 'COLOR']] = df['ANTIGÜEDAD'].apply(
        lambda dias: pd.Series(clasificar_periodicidad(dias)))

    df.rename(columns={'F_OPERACION': 'FECHA DE EGRESO'}, inplace=True)
    colores = df['COLOR'].copy()
    df.drop(columns=['COLOR'], inplace=True)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Egresos')
        workbook = writer.book
        worksheet = writer.sheets['Egresos']

        color_map = {
            'green': '#C6EFCE',
            'yellow': '#FFEB9C',
            'orange': '#F4B084',
            'lightcoral': '#F08080',
            'red': '#FFC7CE',
            'blue': '#BDD7EE',
            'gray': '#D9D9D9'
        }

        col_index = df.columns.get_loc("PERIODICIDAD")

        for row_idx, color in enumerate(colores, start=1):
            fmt = workbook.add_format({'bg_color': color_map.get(color, '#FFFFFF'), 'border': 1})
            worksheet.write(row_idx, col_index, df.loc[row_idx - 1, 'PERIODICIDAD'], fmt)

    output.seek(0)
    return output


@app.route('/tracking', methods=['GET', 'POST'])
@login_required
def tracking():
    movimientos = None

    if request.method == 'POST':
        nro_serie = sanitizar_entrada(request.form.get('nro_serie', ''))

        if not nro_serie:
            flash('Debe ingresar un número de serie', 'warning')
            return render_template('tracking.html', movimientos=None)

        usuario = session.get("usuario")

        movimientos = ejecutar_consulta(TRACKING_POR_SERIAL, [usuario, nro_serie])

        if movimientos.empty:
            flash(f'No se encontraron movimientos para el serial: {nro_serie}', 'info')

    return render_template('tracking.html', movimientos=movimientos)


@app.route('/api/stats')
@login_required
def get_stats():
    """API para estadísticas en tiempo real (solo visual)"""
    usuario = session.get('usuario')
    try:
        # Stock total
        stock_query = """
            SELECT COUNT(*) as total 
            FROM [GTWV400].[dbo].[VSTOCKEP] 
            WHERE [COD. CLIENTE] = ?
        """
        stock_total = ejecutar_consulta(stock_query, [usuario]).iloc[0]['total']

        # Ingresos hoy
        hoy = datetime.datetime.now().strftime('%Y-%m-%d')
        ingresos_query = """
            SELECT COUNT(*) as total 
            FROM [GTWV400].[dbo].[VIEW_WEB_INGRESO_DETALLADO] 
            WHERE CLIENTE_ID = ? AND CAST(FECHA_INGRESO AS DATE) = ?
        """
        ingresos_hoy = ejecutar_consulta(ingresos_query, [usuario, hoy]).iloc[0]['total']

        return jsonify({
            'stock_total': int(stock_total),
            'ingresos_hoy': int(ingresos_hoy),
            'ultima_actualizacion': datetime.datetime.now().strftime('%H:%M:%S')
        })
    except Exception as e:
        logger.error(f"Error en API stats: {str(e)}")
        return jsonify({'error': 'Error al obtener estadísticas'}), 500



# ============================================
# RUTAS DE ARCHIVOS (INVENTARIO)
# ============================================

BASE_INVENTARIO = Config.BASE_INVENTARIO


@app.route('/descargar-inventario')
@login_required
def listar_ciclicos():
    cliente = session.get('cliente')
    if not cliente:
        return redirect(url_for('login'))

    ruta_cliente = os.path.join(BASE_INVENTARIO, cliente)
    if not os.path.exists(ruta_cliente):
        flash(f'No se encontró la carpeta para el cliente: {cliente}', 'warning')
        return render_template('ciclicos.html', carpetas=[])

    try:
        subcarpetas = [nombre for nombre in os.listdir(ruta_cliente)
                       if os.path.isdir(os.path.join(ruta_cliente, nombre))]
    except Exception as e:
        logger.error(f"Error listando carpetas: {str(e)}")
        flash('Error al acceder a los archivos', 'error')
        subcarpetas = []

    return render_template('ciclicos.html', carpetas=subcarpetas, cliente=cliente)


@app.route('/descargar-inventario/<ciclico>')
@login_required
def listar_archivos(ciclico):
    cliente = session.get('cliente')
    if not cliente:
        return redirect(url_for('login'))

    if '..' in ciclico or '/' in ciclico or '\\' in ciclico:
        abort(403)

    ruta = os.path.join(BASE_INVENTARIO, cliente, ciclico)
    ruta_real = os.path.realpath(ruta)
    base_real = os.path.realpath(os.path.join(BASE_INVENTARIO, cliente))

    if not ruta_real.startswith(base_real):
        abort(403)

    if not os.path.exists(ruta):
        flash(f'No se encontró la carpeta {ciclico}', 'warning')
        return redirect(url_for('listar_ciclicos'))

    try:
        archivos = [f for f in os.listdir(ruta) if os.path.isfile(os.path.join(ruta, f))]
    except Exception as e:
        logger.error(f"Error listando archivos: {str(e)}")
        flash('Error al acceder a los archivos', 'error')
        archivos = []

    return render_template('archivos.html', archivos=archivos, ciclico=ciclico, cliente=cliente)


@app.route('/descargar-inventario/<ciclico>/<archivo>')
@login_required
def descargar_archivo(ciclico, archivo):
    cliente = session.get('cliente')
    if not cliente:
        return redirect(url_for('login'))

    if '..' in ciclico or '/' in ciclico or '\\' in ciclico:
        abort(403)
    if '..' in archivo or '/' in archivo or '\\' in archivo:
        abort(403)

    ruta = os.path.join(BASE_INVENTARIO, cliente, ciclico)
    archivo_path = os.path.join(ruta, archivo)

    ruta_real = os.path.realpath(archivo_path)
    base_real = os.path.realpath(os.path.join(BASE_INVENTARIO, cliente))

    if not ruta_real.startswith(base_real):
        abort(403)

    if not os.path.isfile(archivo_path):
        abort(404)

    return send_from_directory(ruta, archivo, as_attachment=True)


# ============================================
# PROTEGER ARCHIVOS SENSIBLES
# ============================================

@app.route('/usuarios.json')
@app.route('/.env')
@app.route('/queries.py')
@app.route('/config.py')
def deny_sensitive_files():
    """Niega el acceso a archivos sensibles"""
    abort(404)


# ============================================
# LOGOUT Y ERRORES
# ============================================

@app.route('/logout')
def logout():
    usuario = session.get('usuario', 'Desconocido')
    log_acceso(f"{usuario} - LOGOUT", intento_exitoso=True)
    session.clear()
    flash('Sesión cerrada correctamente', 'info')
    return redirect(url_for('login'))


@app.errorhandler(404)
def not_found_error(error):
    logger.warning(f"404 error: {request.path}")
    return "Página no encontrada", 404


@app.errorhandler(500)
def internal_error(error):
    logger.error(f"500 error: {str(error)}")
    return "Error interno del servidor", 500


@app.errorhandler(403)
def forbidden_error(error):
    logger.warning(f"403 error: {request.path} desde IP {request.remote_addr}")
    return "Acceso prohibido", 403


# ============================================
# MAIN
# ============================================

if __name__ == '__main__':
    from waitress import serve

    logger.info("Iniciando aplicación en modo producción con Waitress")
    serve(app, host='0.0.0.0', port=5050)