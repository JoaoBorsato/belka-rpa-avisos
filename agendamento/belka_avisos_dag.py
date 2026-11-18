"""
Belka · DAG do robô de avisos oficiais (Airflow 3) — opcional.

Roda todo dia às 06:45, depois da coleta e do processamento da Belka, para que a comparação use o
belka_mvp.json mais recente. Para usar, monte este repositório em /opt/airflow/belka-rpa-avisos e copie
este arquivo para a pasta dags/ do Airflow.

O robô também roda sozinho, fora do Airflow:  python -m belka_avisos
"""
import sys
from datetime import timedelta
from pathlib import Path

import pendulum
from airflow.exceptions import AirflowException
from airflow.sdk import DAG, task

RAIZ = Path("/opt/airflow/belka-rpa-avisos")


@task
def executar_robo() -> dict:
    if str(RAIZ) not in sys.path:
        sys.path.insert(0, str(RAIZ))
    from belka_avisos.robo import FALHA, executar

    r = executar(RAIZ)
    if r.status == FALHA:
        # falha visível no Airflow (nova tentativa); o arquivo anterior do MVP continua publicado
        raise AirflowException(f"Belka avisos falhou: {r.relatorio['erro']} (relatório {r.caminho_relatorio})")
    return {"status": r.status, "pendencias": len(r.relatorio["pendencias"]),
            "avisos_vigentes": r.relatorio["publicacao"].get("avisos_vigentes", 0)}


with DAG(
    dag_id="belka_avisos",
    description="Robô Belka: avisos oficiais do INMET -> avisos_oficiais.json do MVP + comparação com a Belka",
    schedule="45 6 * * *",
    start_date=pendulum.datetime(2026, 11, 1, tz="America/Sao_Paulo"),
    catchup=False,
    max_active_runs=1,
    default_args={"owner": "belka", "retries": 1, "retry_delay": timedelta(minutes=10)},
    tags=["belka", "gs-2026", "rpa"],
) as dag:
    executar_robo()
