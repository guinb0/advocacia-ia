from app.agente import rotas


def test_seletor_de_estilo_expoe_somente_as_quatro_acoes_ativas(monkeypatch) -> None:
    class ClienteFalso:
        def taxonomia(self):
            return {
                "items": [
                    {"code": "LABOR.DAMAGES", "label": "Danos"},
                    {"code": "LABOR.OCCUPATIONAL_HEALTH.WORK_ACCIDENT", "label": "Acidente"},
                    {"code": "SOCIAL_SECURITY.BENEFIT.ACCIDENT_ALLOWANCE", "label": "Auxílio-acidente"},
                    {"code": "LABOR.OCCUPATIONAL_HEALTH.OCCUPATIONAL_DISEASE", "label": "Doença"},
                    {"code": "LABOR.OCCUPATIONAL_HEALTH.WORK_ACCIDENT.CORREIOS", "label": "Correios"},
                    {"code": "LABOR.OCCUPATIONAL_HEALTH.CAUSAL_NEXUS", "label": "Nexo"},
                ]
            }

    monkeypatch.setattr(rotas, "Cliente", ClienteFalso)

    resultado = rotas.taxonomia_de_estilo()

    assert [item["code"] for item in resultado["items"]] == [
        "LABOR.OCCUPATIONAL_HEALTH.WORK_ACCIDENT.CORREIOS",
        "LABOR.OCCUPATIONAL_HEALTH.WORK_ACCIDENT",
        "LABOR.OCCUPATIONAL_HEALTH.OCCUPATIONAL_DISEASE",
        "SOCIAL_SECURITY.BENEFIT.ACCIDENT_ALLOWANCE",
    ]
