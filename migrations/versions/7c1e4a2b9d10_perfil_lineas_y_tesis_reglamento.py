"""perfil academico, lineas de investigacion y tesis segun reglamento 2024

Revision ID: 7c1e4a2b9d10
Revises: 23a884bb9c55
Create Date: 2026-11-02

- Catalogo de areas, lineas y temas de investigacion de la EPIS (datos oficiales).
- Perfil academico del docente (prelacion, colegiatura, licencias) e historial de cambios.
- Tesis rehecha segun el Reglamento Marco 256-CU-2024-UAC (etapas, dictamenes por ronda,
  resoluciones). Las tablas de tesis anteriores se reemplazan: la migracion se detiene si
  contienen datos.
"""
from alembic import op
import sqlalchemy as sa

revision = '7c1e4a2b9d10'
down_revision = '23a884bb9c55'
branch_labels = None
depends_on = None

TABLAS_TESIS_ANTERIORES = ['tesis_eventos', 'tesis_versiones', 'tesis_miembros', 'tesis_estudiantes', 'tesis']


def upgrade():
    conn = op.get_bind()
    for tabla in ('tesis', 'tesis_miembros', 'tesis_versiones'):
        n = conn.execute(sa.text(f'SELECT COUNT(*) FROM {tabla}')).scalar()
        if n:
            raise RuntimeError(f'La tabla {tabla} tiene {n} registros: migre esos datos manualmente antes de actualizar.')

    # ---------- Catalogo de lineas de investigacion ----------
    op.create_table('areas_investigacion',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('nombre', sa.String(length=150), nullable=False),
    sa.Column('orden', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_areas_investigacion')),
    sa.UniqueConstraint('nombre', name=op.f('uq_areas_investigacion_nombre'))
    )
    op.create_table('feriados',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('fecha', sa.Date(), nullable=False),
    sa.Column('descripcion', sa.String(length=150), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_feriados')),
    sa.UniqueConstraint('fecha', name=op.f('uq_feriados_fecha'))
    )
    op.create_table('parametros',
    sa.Column('clave', sa.String(length=60), nullable=False),
    sa.Column('valor', sa.String(length=200), nullable=False),
    sa.PrimaryKeyConstraint('clave', name=op.f('pk_parametros'))
    )
    op.create_table('lineas_investigacion',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('area_id', sa.Integer(), nullable=False),
    sa.Column('nombre', sa.String(length=150), nullable=False),
    sa.Column('orden', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['area_id'], ['areas_investigacion.id'], name=op.f('fk_lineas_investigacion_area_id_areas_investigacion'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_lineas_investigacion')),
    sa.UniqueConstraint('area_id', 'nombre', name='uq_linea_area_nombre')
    )
    with op.batch_alter_table('lineas_investigacion', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_lineas_investigacion_area_id'), ['area_id'], unique=False)
    op.create_table('temas_investigacion',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('linea_id', sa.Integer(), nullable=False),
    sa.Column('nombre', sa.String(length=200), nullable=False),
    sa.Column('orden', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['linea_id'], ['lineas_investigacion.id'], name=op.f('fk_temas_investigacion_linea_id_lineas_investigacion'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_temas_investigacion')),
    sa.UniqueConstraint('linea_id', 'nombre', name='uq_tema_linea_nombre')
    )
    with op.batch_alter_table('temas_investigacion', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_temas_investigacion_linea_id'), ['linea_id'], unique=False)

    areas = sa.table('areas_investigacion', sa.column('id', sa.Integer), sa.column('nombre', sa.String), sa.column('orden', sa.Integer))
    lineas = sa.table('lineas_investigacion', sa.column('id', sa.Integer), sa.column('area_id', sa.Integer),
                      sa.column('nombre', sa.String), sa.column('orden', sa.Integer))
    temas = sa.table('temas_investigacion', sa.column('id', sa.Integer), sa.column('linea_id', sa.Integer),
                     sa.column('nombre', sa.String), sa.column('orden', sa.Integer))
    op.bulk_insert(areas, [{'id': 1, 'nombre': 'Tecnologías de Información', 'orden': 1}, {'id': 2, 'nombre': 'Tecnologías de Comunicación', 'orden': 2}, {'id': 3, 'nombre': 'Organización Empresarial y Gestión de Información', 'orden': 3}])
    op.bulk_insert(lineas, [{'id': 1, 'area_id': 1, 'nombre': 'Desarrollo de software', 'orden': 1}, {'id': 2, 'area_id': 1, 'nombre': 'Ciencia de datos', 'orden': 2}, {'id': 3, 'area_id': 1, 'nombre': 'Algorítmica', 'orden': 3}, {'id': 4, 'area_id': 2, 'nombre': 'Comunicaciones Unificadas', 'orden': 1}, {'id': 5, 'area_id': 2, 'nombre': 'Seguridad en tecnologías de información y comunicación', 'orden': 2}, {'id': 6, 'area_id': 2, 'nombre': 'Sistemas de control y monitoreo', 'orden': 3}, {'id': 7, 'area_id': 3, 'nombre': 'Sistemas de información', 'orden': 1}, {'id': 8, 'area_id': 3, 'nombre': 'Sociedad de información', 'orden': 2}])
    op.bulk_insert(temas, [{'id': 1, 'linea_id': 1, 'nombre': 'Automatización de procesos', 'orden': 1}, {'id': 2, 'linea_id': 1, 'nombre': 'Desarrollo de aplicaciones usando inteligencia artificial', 'orden': 2}, {'id': 3, 'linea_id': 1, 'nombre': 'Realidad virtual', 'orden': 3}, {'id': 4, 'linea_id': 1, 'nombre': 'Sistemas de información geográfica', 'orden': 4}, {'id': 5, 'linea_id': 1, 'nombre': 'Investigación asistida por computadora', 'orden': 5}, {'id': 6, 'linea_id': 2, 'nombre': 'Modelación y simulación usando modelos matemáticos', 'orden': 1}, {'id': 7, 'linea_id': 2, 'nombre': 'Inteligencia de negocios', 'orden': 2}, {'id': 8, 'linea_id': 2, 'nombre': 'Tratamiento de grandes cantidades de datos', 'orden': 3}, {'id': 9, 'linea_id': 2, 'nombre': 'Seguridad de información', 'orden': 4}, {'id': 10, 'linea_id': 2, 'nombre': 'Almacenamiento y recuperación de la información', 'orden': 5}, {'id': 11, 'linea_id': 2, 'nombre': 'Machine learning', 'orden': 6}, {'id': 12, 'linea_id': 3, 'nombre': 'Algoritmos de migración', 'orden': 1}, {'id': 13, 'linea_id': 3, 'nombre': 'Algoritmos numéricos', 'orden': 2}, {'id': 14, 'linea_id': 3, 'nombre': 'Biotecnología', 'orden': 3}, {'id': 15, 'linea_id': 3, 'nombre': 'Matemática aplicada computacional', 'orden': 4}, {'id': 16, 'linea_id': 3, 'nombre': 'Técnica algorítmica de juegos', 'orden': 5}, {'id': 17, 'linea_id': 4, 'nombre': 'Contenedores', 'orden': 1}, {'id': 18, 'linea_id': 4, 'nombre': 'Virtualización', 'orden': 2}, {'id': 19, 'linea_id': 4, 'nombre': 'Data center', 'orden': 3}, {'id': 20, 'linea_id': 4, 'nombre': 'Protocolos de comunicación', 'orden': 4}, {'id': 21, 'linea_id': 4, 'nombre': 'Normatividad', 'orden': 5}, {'id': 22, 'linea_id': 4, 'nombre': 'Servicios de red', 'orden': 6}, {'id': 23, 'linea_id': 4, 'nombre': 'Clustering', 'orden': 7}, {'id': 24, 'linea_id': 4, 'nombre': 'Infraestructura', 'orden': 8}, {'id': 25, 'linea_id': 5, 'nombre': 'Seguridad de redes', 'orden': 1}, {'id': 26, 'linea_id': 5, 'nombre': 'Normativas', 'orden': 2}, {'id': 27, 'linea_id': 6, 'nombre': 'Sistemas embebidos', 'orden': 1}, {'id': 28, 'linea_id': 6, 'nombre': 'Scada', 'orden': 2}, {'id': 29, 'linea_id': 6, 'nombre': 'Domótica', 'orden': 3}, {'id': 30, 'linea_id': 7, 'nombre': 'Gestión de servicios de TI (ITIL, COBIT)', 'orden': 1}, {'id': 31, 'linea_id': 7, 'nombre': 'Gestión de infraestructura de TI', 'orden': 2}, {'id': 32, 'linea_id': 7, 'nombre': 'Gestión estratégica de TI', 'orden': 3}, {'id': 33, 'linea_id': 7, 'nombre': 'Gestión de proyectos en sistemas de información', 'orden': 4}, {'id': 34, 'linea_id': 7, 'nombre': 'Auditoría de sistemas de información', 'orden': 5}, {'id': 35, 'linea_id': 7, 'nombre': 'Gestión de la seguridad de sistemas de información', 'orden': 6}, {'id': 36, 'linea_id': 7, 'nombre': 'Gestión de procesos de negocio', 'orden': 7}, {'id': 37, 'linea_id': 7, 'nombre': 'Gestión de conocimiento', 'orden': 8}, {'id': 38, 'linea_id': 7, 'nombre': 'Gestión del cambio organizacional', 'orden': 9}, {'id': 39, 'linea_id': 7, 'nombre': 'Gestión de información', 'orden': 10}, {'id': 40, 'linea_id': 7, 'nombre': 'Inteligencia de negocios', 'orden': 11}, {'id': 41, 'linea_id': 7, 'nombre': 'Modelado y simulación de sistemas', 'orden': 12}, {'id': 42, 'linea_id': 7, 'nombre': 'Inteligencia artificial', 'orden': 13}, {'id': 43, 'linea_id': 7, 'nombre': 'Calidad de sistemas de información', 'orden': 14}, {'id': 44, 'linea_id': 7, 'nombre': 'Metodologías del ciclo de vida de desarrollo de sistemas de información', 'orden': 15}, {'id': 45, 'linea_id': 8, 'nombre': 'Alfabetización digital', 'orden': 1}, {'id': 46, 'linea_id': 8, 'nombre': 'Inclusión digital', 'orden': 2}, {'id': 47, 'linea_id': 8, 'nombre': 'Gobierno electrónico', 'orden': 3}, {'id': 48, 'linea_id': 8, 'nombre': 'Elearning', 'orden': 4}, {'id': 49, 'linea_id': 8, 'nombre': 'Esalud', 'orden': 5}, {'id': 50, 'linea_id': 8, 'nombre': 'Agricultura', 'orden': 6}, {'id': 51, 'linea_id': 8, 'nombre': 'Ecommerce', 'orden': 7}, {'id': 52, 'linea_id': 8, 'nombre': 'Sistemas de información geográficos', 'orden': 8}, {'id': 53, 'linea_id': 8, 'nombre': 'Marketing digital', 'orden': 9}])

    # ---------- Perfil academico del docente ----------
    with op.batch_alter_table('docentes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('condicion', sa.String(length=12), nullable=True))
        batch_op.add_column(sa.Column('es_autoridad', sa.Boolean(), server_default=sa.false(), nullable=False))
        batch_op.add_column(sa.Column('cargo_autoridad', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('colegiatura_numero', sa.String(length=30), nullable=True))
        batch_op.add_column(sa.Column('colegiatura_anio', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('experiencia_anios', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('licencia_desde', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('licencia_hasta', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('linea_principal_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('perfil_actualizado_en', sa.DateTime(), nullable=True))
        batch_op.create_foreign_key(batch_op.f('fk_docentes_linea_principal_id_lineas_investigacion'),
                                    'lineas_investigacion', ['linea_principal_id'], ['id'], ondelete='SET NULL')
        batch_op.create_check_constraint('condicion_valida', "condicion IS NULL OR condicion IN ('ordinario','contratado')")
        batch_op.create_check_constraint('colegiatura_valida', 'colegiatura_anio IS NULL OR (colegiatura_anio BETWEEN 1950 AND 2100)')
        batch_op.create_check_constraint('experiencia_valida', 'experiencia_anios IS NULL OR (experiencia_anios BETWEEN 0 AND 70)')
        batch_op.create_check_constraint('licencia_valida', 'licencia_hasta IS NULL OR licencia_desde IS NULL OR licencia_hasta >= licencia_desde')

    with op.batch_alter_table('semestres', schema=None) as batch_op:
        batch_op.add_column(sa.Column('fecha_inicio', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('fecha_fin', sa.Date(), nullable=True))

    op.create_table('docente_lineas',
    sa.Column('docente_id', sa.Integer(), nullable=False),
    sa.Column('linea_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['docente_id'], ['docentes.id'], name=op.f('fk_docente_lineas_docente_id_docentes'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['linea_id'], ['lineas_investigacion.id'], name=op.f('fk_docente_lineas_linea_id_lineas_investigacion'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('docente_id', 'linea_id', name=op.f('pk_docente_lineas'))
    )
    op.create_table('docente_temas',
    sa.Column('docente_id', sa.Integer(), nullable=False),
    sa.Column('tema_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['docente_id'], ['docentes.id'], name=op.f('fk_docente_temas_docente_id_docentes'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tema_id'], ['temas_investigacion.id'], name=op.f('fk_docente_temas_tema_id_temas_investigacion'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('docente_id', 'tema_id', name=op.f('pk_docente_temas'))
    )
    op.create_table('cambios_perfil',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('docente_id', sa.Integer(), nullable=False),
    sa.Column('campo', sa.String(length=40), nullable=False),
    sa.Column('valor_anterior', sa.String(length=300), nullable=True),
    sa.Column('valor_nuevo', sa.String(length=300), nullable=True),
    sa.Column('estado', sa.String(length=10), nullable=False),
    sa.Column('motivo', sa.Text(), nullable=True),
    sa.Column('archivo_ruta', sa.String(length=300), nullable=True),
    sa.Column('archivo_nombre', sa.String(length=255), nullable=True),
    sa.Column('solicitado_por_id', sa.Integer(), nullable=True),
    sa.Column('revisado_por_id', sa.Integer(), nullable=True),
    sa.Column('creado_en', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('revisado_en', sa.DateTime(), nullable=True),
    sa.CheckConstraint("estado IN ('pendiente','aprobado','rechazado','directo')", name=op.f('ck_cambios_perfil_estado_valido')),
    sa.ForeignKeyConstraint(['docente_id'], ['docentes.id'], name=op.f('fk_cambios_perfil_docente_id_docentes'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['revisado_por_id'], ['usuarios.id'], name=op.f('fk_cambios_perfil_revisado_por_id_usuarios'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['solicitado_por_id'], ['usuarios.id'], name=op.f('fk_cambios_perfil_solicitado_por_id_usuarios'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_cambios_perfil'))
    )
    with op.batch_alter_table('cambios_perfil', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_cambios_perfil_docente_id'), ['docente_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_cambios_perfil_estado'), ['estado'], unique=False)

    # ---------- Tesis (estructura del Reglamento 2024) ----------
    for tabla in TABLAS_TESIS_ANTERIORES:
        op.drop_table(tabla)
    op.create_table('tesis',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('codigo', sa.String(length=30), nullable=False),
    sa.Column('titulo', sa.String(length=600), nullable=False),
    sa.Column('resumen', sa.Text(), nullable=True),
    sa.Column('palabras_clave', sa.String(length=300), nullable=True),
    sa.Column('area_id', sa.Integer(), nullable=True),
    sa.Column('linea_id', sa.Integer(), nullable=True),
    sa.Column('modalidad', sa.String(length=12), nullable=False),
    sa.Column('regimen', sa.String(length=10), nullable=False),
    sa.Column('etapa', sa.String(length=15), nullable=False),
    sa.Column('decision_pendiente', sa.String(length=200), nullable=True),
    sa.Column('semestre_id', sa.Integer(), nullable=True),
    sa.Column('fecha_registro', sa.Date(), nullable=True),
    sa.Column('fecha_inscripcion', sa.Date(), nullable=True),
    sa.Column('fecha_limite_entrega', sa.Date(), nullable=True),
    sa.Column('plazo_ampliado', sa.Boolean(), nullable=False),
    sa.Column('fecha_sustentacion', sa.DateTime(), nullable=True),
    sa.Column('lugar_sustentacion', sa.String(length=200), nullable=True),
    sa.Column('modalidad_sustentacion', sa.String(length=10), nullable=True),
    sa.Column('numero_sustentacion', sa.Integer(), nullable=False),
    sa.Column('nota_sustentacion', sa.Integer(), nullable=True),
    sa.Column('calificacion', sa.String(length=60), nullable=True),
    sa.Column('creado_por_id', sa.Integer(), nullable=True),
    sa.Column('creado_en', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('actualizado_en', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint("etapa IN ('asesor','proyecto','inscripcion','desarrollo','dictamen','apto','sustentacion','observaciones','titulado','rechazada','anulada')", name=op.f('ck_tesis_etapa_valida')),
    sa.CheckConstraint("modalidad IN ('tesis','suficiencia')", name=op.f('ck_tesis_modalidad_valida')),
    sa.CheckConstraint("regimen IN ('vigente','anterior')", name=op.f('ck_tesis_regimen_valido')),
    sa.CheckConstraint('nota_sustentacion IS NULL OR (nota_sustentacion BETWEEN 0 AND 20)', name=op.f('ck_tesis_nota_rango')),
    sa.ForeignKeyConstraint(['area_id'], ['areas_investigacion.id'], name=op.f('fk_tesis_area_id_areas_investigacion'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['creado_por_id'], ['usuarios.id'], name=op.f('fk_tesis_creado_por_id_usuarios'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['linea_id'], ['lineas_investigacion.id'], name=op.f('fk_tesis_linea_id_lineas_investigacion'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['semestre_id'], ['semestres.id'], name=op.f('fk_tesis_semestre_id_semestres'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tesis')),
    sa.UniqueConstraint('codigo', name=op.f('uq_tesis_codigo'))
    )
    with op.batch_alter_table('tesis', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_tesis_etapa'), ['etapa'], unique=False)
    op.create_table('resoluciones_tesis',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('tesis_id', sa.Integer(), nullable=False),
    sa.Column('tipo', sa.String(length=30), nullable=False),
    sa.Column('numero', sa.String(length=80), nullable=False),
    sa.Column('fecha', sa.Date(), nullable=False),
    sa.Column('registrada_por_id', sa.Integer(), nullable=True),
    sa.Column('creado_en', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['registrada_por_id'], ['usuarios.id'], name=op.f('fk_resoluciones_tesis_registrada_por_id_usuarios'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['tesis_id'], ['tesis.id'], name=op.f('fk_resoluciones_tesis_tesis_id_tesis'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_resoluciones_tesis'))
    )
    with op.batch_alter_table('resoluciones_tesis', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_resoluciones_tesis_tesis_id'), ['tesis_id'], unique=False)
    op.create_table('tesis_estudiantes',
    sa.Column('tesis_id', sa.Integer(), nullable=False),
    sa.Column('estudiante_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['estudiante_id'], ['estudiantes.id'], name=op.f('fk_tesis_estudiantes_estudiante_id_estudiantes'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tesis_id'], ['tesis.id'], name=op.f('fk_tesis_estudiantes_tesis_id_tesis'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('tesis_id', 'estudiante_id', name=op.f('pk_tesis_estudiantes'))
    )
    op.create_table('tesis_eventos',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('tesis_id', sa.Integer(), nullable=False),
    sa.Column('usuario_id', sa.Integer(), nullable=True),
    sa.Column('tipo', sa.String(length=30), nullable=False),
    sa.Column('descripcion', sa.Text(), nullable=False),
    sa.Column('creado_en', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['tesis_id'], ['tesis.id'], name=op.f('fk_tesis_eventos_tesis_id_tesis'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id'], name=op.f('fk_tesis_eventos_usuario_id_usuarios'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tesis_eventos'))
    )
    with op.batch_alter_table('tesis_eventos', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_tesis_eventos_tesis_id'), ['tesis_id'], unique=False)
    op.create_table('tesis_miembros',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('tesis_id', sa.Integer(), nullable=False),
    sa.Column('docente_id', sa.Integer(), nullable=False),
    sa.Column('rol', sa.String(length=15), nullable=False),
    sa.Column('etapa_ingreso', sa.String(length=10), nullable=True),
    sa.Column('estado_designacion', sa.String(length=12), nullable=False),
    sa.Column('orden_prelacion', sa.Integer(), nullable=True),
    sa.Column('automatico', sa.Boolean(), nullable=False),
    sa.Column('puntaje', sa.Float(), nullable=True),
    sa.Column('motivos', sa.Text(), nullable=True),
    sa.Column('fecha_designacion', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('fecha_respuesta', sa.DateTime(), nullable=True),
    sa.Column('motivo_impedimento', sa.Text(), nullable=True),
    sa.Column('nota_sustentacion', sa.Float(), nullable=True),
    sa.Column('asignado_por_id', sa.Integer(), nullable=True),
    sa.Column('creado_en', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('actualizado_en', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint("estado_designacion IN ('propuesto','aceptado','impedimento','reemplazado','retirado')", name=op.f('ck_tesis_miembros_designacion_valida')),
    sa.CheckConstraint("rol IN ('asesor','coasesor','dictaminante','dirimente','replicante')", name=op.f('ck_tesis_miembros_rol_valido')),
    sa.CheckConstraint('nota_sustentacion IS NULL OR (nota_sustentacion BETWEEN 0 AND 20)', name=op.f('ck_tesis_miembros_nota_rango')),
    sa.ForeignKeyConstraint(['asignado_por_id'], ['usuarios.id'], name=op.f('fk_tesis_miembros_asignado_por_id_usuarios'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['docente_id'], ['docentes.id'], name=op.f('fk_tesis_miembros_docente_id_docentes'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tesis_id'], ['tesis.id'], name=op.f('fk_tesis_miembros_tesis_id_tesis'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tesis_miembros')),
    sa.UniqueConstraint('tesis_id', 'docente_id', 'rol', name='uq_tesis_docente_rol')
    )
    with op.batch_alter_table('tesis_miembros', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_tesis_miembros_docente_id'), ['docente_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_tesis_miembros_tesis_id'), ['tesis_id'], unique=False)
    op.create_table('tesis_temas',
    sa.Column('tesis_id', sa.Integer(), nullable=False),
    sa.Column('tema_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['tema_id'], ['temas_investigacion.id'], name=op.f('fk_tesis_temas_tema_id_temas_investigacion'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tesis_id'], ['tesis.id'], name=op.f('fk_tesis_temas_tesis_id_tesis'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('tesis_id', 'tema_id', name=op.f('pk_tesis_temas'))
    )
    op.create_table('tesis_versiones',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('tesis_id', sa.Integer(), nullable=False),
    sa.Column('numero', sa.Integer(), nullable=False),
    sa.Column('etapa', sa.String(length=12), nullable=False),
    sa.Column('archivo_ruta', sa.String(length=300), nullable=False),
    sa.Column('archivo_nombre', sa.String(length=255), nullable=False),
    sa.Column('subsanacion_ruta', sa.String(length=300), nullable=True),
    sa.Column('subsanacion_nombre', sa.String(length=255), nullable=True),
    sa.Column('comentario', sa.Text(), nullable=True),
    sa.Column('subido_por_id', sa.Integer(), nullable=True),
    sa.Column('creado_en', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.CheckConstraint("etapa IN ('proyecto','tesis','final')", name=op.f('ck_tesis_versiones_etapa_valida')),
    sa.ForeignKeyConstraint(['subido_por_id'], ['usuarios.id'], name=op.f('fk_tesis_versiones_subido_por_id_usuarios'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['tesis_id'], ['tesis.id'], name=op.f('fk_tesis_versiones_tesis_id_tesis'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tesis_versiones')),
    sa.UniqueConstraint('tesis_id', 'numero', name='uq_tesis_version_numero')
    )
    with op.batch_alter_table('tesis_versiones', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_tesis_versiones_tesis_id'), ['tesis_id'], unique=False)
    op.create_table('dictamenes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('tesis_id', sa.Integer(), nullable=False),
    sa.Column('miembro_id', sa.Integer(), nullable=False),
    sa.Column('etapa', sa.String(length=10), nullable=False),
    sa.Column('ronda', sa.Integer(), nullable=False),
    sa.Column('resultado', sa.String(length=20), nullable=True),
    sa.Column('observaciones', sa.Text(), nullable=True),
    sa.Column('archivo_ruta', sa.String(length=300), nullable=True),
    sa.Column('archivo_nombre', sa.String(length=255), nullable=True),
    sa.Column('inicio', sa.Date(), nullable=False),
    sa.Column('limite', sa.Date(), nullable=False),
    sa.Column('emitido_en', sa.DateTime(), nullable=True),
    sa.CheckConstraint("etapa IN ('proyecto','tesis')", name=op.f('ck_dictamenes_etapa_valida')),
    sa.CheckConstraint("resultado IS NULL OR resultado IN ('suficiente','con_observaciones','insuficiente')", name=op.f('ck_dictamenes_resultado_valido')),
    sa.ForeignKeyConstraint(['miembro_id'], ['tesis_miembros.id'], name=op.f('fk_dictamenes_miembro_id_tesis_miembros'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tesis_id'], ['tesis.id'], name=op.f('fk_dictamenes_tesis_id_tesis'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_dictamenes')),
    sa.UniqueConstraint('miembro_id', 'etapa', 'ronda', name='uq_dictamen_miembro_ronda')
    )
    with op.batch_alter_table('dictamenes', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_dictamenes_miembro_id'), ['miembro_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_dictamenes_tesis_id'), ['tesis_id'], unique=False)



def downgrade():
    for tabla in ['dictamenes', 'tesis_versiones', 'tesis_temas', 'tesis_miembros', 'tesis_eventos', 'tesis_estudiantes',
                  'resoluciones_tesis', 'tesis', 'cambios_perfil', 'docente_temas', 'docente_lineas']:
        op.drop_table(tabla)
    with op.batch_alter_table('semestres', schema=None) as batch_op:
        batch_op.drop_column('fecha_fin')
        batch_op.drop_column('fecha_inicio')
    with op.batch_alter_table('docentes', schema=None) as batch_op:
        for c in ('licencia_valida', 'experiencia_valida', 'colegiatura_valida', 'condicion_valida'):
            batch_op.drop_constraint(c, type_='check')
        batch_op.drop_constraint(batch_op.f('fk_docentes_linea_principal_id_lineas_investigacion'), type_='foreignkey')
        for c in ('perfil_actualizado_en', 'linea_principal_id', 'licencia_hasta', 'licencia_desde', 'experiencia_anios',
                  'colegiatura_anio', 'colegiatura_numero', 'cargo_autoridad', 'es_autoridad', 'condicion'):
            batch_op.drop_column(c)
    for tabla in ['temas_investigacion', 'lineas_investigacion', 'parametros', 'feriados', 'areas_investigacion']:
        op.drop_table(tabla)
    raise RuntimeError('Las tablas de tesis anteriores no se recrean automaticamente; restaure el respaldo de la base de datos.')
