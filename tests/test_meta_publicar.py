"""meta_publicar.py: publica campanha + conjunto + anúncio PAUSADOS a partir do criativo aprovado.

Rede 100% stubada (FakePublicaApi). HOME temporário. Nenhum arquivo de mídia real.

    python3 -m unittest tests/test_meta_publicar.py
"""
import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import tpa_paths  # noqa: E402
import meta_acoes  # noqa: E402
import meta_publicar  # noqa: E402

CONTA = "act_111111"


class FakePublicaApi(object):
    def __init__(self):
        self.posts = []
        self.estado = {}
        self.falhar_em = None          # sufixo do caminho que deve falhar
        self.video_status = ["processing", "ready"]
        self.nasce_ativo = False       # simula um bug da Meta: nasce ACTIVE
        self.interesses = {"marketing digital": {"id": "6003", "name": "Marketing digital"}}
        self._n = 0

    def _novo(self, prefixo):
        self._n += 1
        return "%s%014d" % (prefixo, self._n)

    def get(self, caminho, params=None):
        params = params or {}
        if caminho == CONTA:
            return {"name": "Conta Teste", "currency": "BRL"}
        if caminho == "search":
            achado = self.interesses.get(params["q"].lower())
            return {"data": [achado] if achado else []}
        if caminho in self.estado:
            alvo = self.estado[caminho]
            if alvo.get("kind") == "video":
                return {"status": {"video_status": self.video_status.pop(0) if len(self.video_status) > 1 else self.video_status[0]}}
            return {"id": caminho, "status": alvo.get("status")}
        raise RuntimeError('Graph API 400: {"error":{"message":"Unsupported get request"}}')

    def post(self, caminho, params, campo_arquivo=None, arquivo=None):
        self.posts.append({"caminho": caminho, "params": copy.deepcopy(params), "campo": campo_arquivo,
                           "arquivo": str(arquivo) if arquivo else None})
        if self.falhar_em and caminho.endswith(self.falhar_em):
            raise RuntimeError('Graph API 400: {"error":{"message":"Parametro invalido (token=EAAsegredo)"}}')
        fim = caminho.split("/")[-1]
        if fim == "adimages":
            return {"images": {"x": {"hash": "hash%03d" % len(self.posts)}}}
        if fim == "advideos":
            novo = self._novo("77")
            self.estado[novo] = {"kind": "video"}
            return {"id": novo}
        prefixo = {"campaigns": "11", "adsets": "22", "adcreatives": "33", "ads": "44"}[fim]
        novo = self._novo(prefixo)
        status = params.get("status")
        if self.nasce_ativo and status == "PAUSED":
            status = "ACTIVE"
        self.estado[novo] = {"status": status}
        return {"id": novo}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="tpa-publicar-"))
        self.paths = tpa_paths.active_paths(env={"OPERACAO_IA_HOME": str(self.tmp / "base")},
                                            file=str(self.tmp / "nao-instalado" / "x.py"))
        (self.paths.home / "config").mkdir(parents=True, exist_ok=True)
        self.escreve_env(pagina="555000111", pixel="777000222")
        self.api = FakePublicaApi()
        (self.tmp / "criativo.png").write_bytes(b"\x89PNG fake")
        (self.tmp / "capa.jpg").write_bytes(b"jpg fake")
        (self.tmp / "video.mp4").write_bytes(b"mp4 fake")
        self.spec = copy.deepcopy(meta_publicar.EXEMPLO)
        self.spec["criativo"]["arquivo"] = "criativo.png"
        self.saida = []

    def tearDown(self):
        shutil.rmtree(str(self.tmp), ignore_errors=True)

    def escreve_env(self, pagina="", pixel=""):
        self.paths.meta_env.write_text(
            "META_ACCESS_TOKEN=EAAsegredo\nMETA_AD_ACCOUNT_ID=%s\nMETA_PAGE_ID=%s\nMETA_PIXEL_ID=%s\n" % (CONTA, pagina, pixel),
            encoding="utf-8")

    def out(self, texto=""):
        self.saida.append(str(texto))

    def rodar(self, *extra):
        arq = self.tmp / "campanha.json"
        arq.write_text(json.dumps(self.spec), encoding="utf-8")
        self.saida = []
        codigo = meta_publicar.main([str(arq)] + list(extra), api=self.api, paths=self.paths,
                                    out=self.out, sleep=lambda s: None)
        return codigo, "\n".join(self.saida)

    def log(self):
        caminho = Path(self.paths.logs) / meta_acoes.LOG_NAME
        if not caminho.exists():
            return []
        return [json.loads(l) for l in caminho.read_text(encoding="utf-8").splitlines() if l.strip()]

    def posts_em(self, fim):
        return [p for p in self.api.posts if p["caminho"].endswith(fim)]


class TestDryRun(Base):
    def test_sem_confirmar_so_mostra_resumo_e_nao_escreve_nada(self):
        codigo, texto = self.rodar()
        self.assertEqual(codigo, 0)
        self.assertEqual(self.api.posts, [])
        self.assertEqual(self.log(), [])
        for trecho in ("RESUMO", CONTA, "R$ 30,00", "daily_budget=3000", "BR", "Marketing digital", "criativo.png",
                       "PAUSADOS", "--confirmar"):
            self.assertIn(trecho, texto)

    def test_exemplo_imprime_json_valido(self):
        saida = []
        self.assertEqual(meta_publicar.main(["--exemplo"], out=saida.append), 0)
        dado = json.loads("\n".join(saida))
        self.assertEqual(dado["objetivo"], "leads")


class TestPublicar(Base):
    def test_cria_tudo_pausado_na_ordem_certa(self):
        codigo, texto = self.rodar("--confirmar")
        self.assertEqual(codigo, 0, texto)
        ordem = [p["caminho"].split("/")[-1] for p in self.api.posts]
        self.assertEqual(ordem, ["adimages", "campaigns", "adsets", "adcreatives", "ads"])
        for fim in ("campaigns", "adsets", "ads"):
            (p,) = self.posts_em(fim)
            self.assertEqual(p["params"]["status"], "PAUSED", fim)
        self.assertIn("tudo PAUSADO", texto)
        self.assertIn("meta_acoes.py ativar", texto)
        (linha,) = self.log()
        self.assertEqual((linha["acao"], linha["resultado"], linha["verificado"]), ("publicar", "ok", True))
        self.assertEqual(set(linha["ids"]), {"image_hash", "campaign_id", "adset_id", "creative_id", "ad_id"})

    def test_payload_do_conjunto_leads(self):
        self.rodar("--confirmar")
        (conj,) = self.posts_em("adsets")
        p = conj["params"]
        self.assertEqual(p["daily_budget"], "3000")
        self.assertEqual(p["optimization_goal"], "OFFSITE_CONVERSIONS")
        self.assertEqual(p["promoted_object"], {"pixel_id": "777000222", "custom_event_type": "LEAD"})
        self.assertEqual(p["targeting"]["geo_locations"], {"countries": ["BR"]})
        self.assertEqual(p["targeting"]["flexible_spec"], [{"interests": [{"id": "6003", "name": "Marketing digital"}]}])
        self.assertNotIn("genders", p["targeting"])
        (camp,) = self.posts_em("campaigns")
        self.assertEqual(camp["params"]["objective"], "OUTCOME_LEADS")
        self.assertEqual(camp["params"]["special_ad_categories"], [])

    def test_trafego_nao_exige_pixel(self):
        self.escreve_env(pagina="555000111", pixel="")
        self.spec["objetivo"] = "trafego"
        codigo, _ = self.rodar("--confirmar")
        self.assertEqual(codigo, 0)
        (conj,) = self.posts_em("adsets")
        self.assertEqual(conj["params"]["optimization_goal"], "LINK_CLICKS")
        self.assertNotIn("promoted_object", conj["params"])

    def test_leads_sem_pixel_recusa_antes_de_criar(self):
        self.escreve_env(pagina="555000111", pixel="")
        codigo, texto = self.rodar("--confirmar")
        self.assertEqual(codigo, 1)
        self.assertIn("META_PIXEL_ID", texto)
        self.assertEqual(self.api.posts, [])

    def test_sem_pagina_recusa(self):
        self.escreve_env(pagina="", pixel="777000222")
        codigo, texto = self.rodar("--confirmar")
        self.assertEqual(codigo, 1)
        self.assertIn("META_PAGE_ID", texto)
        self.assertEqual(self.api.posts, [])

    def test_criativo_de_imagem_usa_link_data_com_cta(self):
        self.rodar("--confirmar")
        (cri,) = self.posts_em("adcreatives")
        oss = cri["params"]["object_story_spec"]
        self.assertEqual(oss["page_id"], "555000111")
        ld = oss["link_data"]
        self.assertEqual(ld["link"], self.spec["criativo"]["link"])
        self.assertEqual(ld["message"], self.spec["criativo"]["texto"])
        self.assertEqual(ld["call_to_action"]["type"], "LEARN_MORE")
        self.assertTrue(ld["image_hash"].startswith("hash"))

    def test_video_envia_capa_e_espera_processar(self):
        self.spec["criativo"].update({"tipo": "video", "arquivo": "video.mp4", "thumbnail": "capa.jpg"})
        codigo, texto = self.rodar("--confirmar")
        self.assertEqual(codigo, 0, texto)
        (vid,) = self.posts_em("advideos")
        self.assertEqual(vid["campo"], "source")
        (cri,) = self.posts_em("adcreatives")
        vd = cri["params"]["object_story_spec"]["video_data"]
        self.assertTrue(vd["video_id"].startswith("77"))
        self.assertTrue(vd["image_hash"].startswith("hash"))

    def test_video_com_erro_de_processamento_para_antes_da_campanha(self):
        self.spec["criativo"].update({"tipo": "video", "arquivo": "video.mp4", "thumbnail": "capa.jpg"})
        self.api.video_status = ["error"]
        codigo, texto = self.rodar("--confirmar")
        self.assertEqual(codigo, 1)
        self.assertIn("recusou o vídeo", texto)
        self.assertEqual(self.posts_em("campaigns"), [])

    def test_video_timeout_nomeado_e_respeitado(self):
        self.spec["criativo"].update({"tipo": "video", "arquivo": "video.mp4", "thumbnail": "capa.jpg"})
        self.api.video_status = ["processing"]
        relogio = iter([0, 0, 10 ** 6, 10 ** 6, 10 ** 6])
        ctx = meta_acoes.montar_contexto(api=self.api, paths=self.paths)
        with self.assertRaises(meta_acoes.AcaoErro) as e:
            meta_publicar.sobe_video(ctx, self.tmp / "video.mp4", lambda *_: None, sleep=lambda s: None,
                                     relogio=lambda: next(relogio))
        self.assertIn("ZX_TPA_VIDEO_TIMEOUT", str(e.exception))
        self.assertGreaterEqual(meta_publicar.VIDEO_TIMEOUT, 1)

    def test_falha_no_meio_lista_o_que_ja_foi_criado_e_nao_apaga(self):
        self.api.falhar_em = "adcreatives"
        codigo, texto = self.rodar("--confirmar")
        self.assertEqual(codigo, 1)
        self.assertIn("Já criado na Meta", texto)
        self.assertIn("campaign_id=", texto)
        self.assertIn("adset_id=", texto)
        self.assertNotIn("EAAsegredo", texto)
        self.assertEqual(self.posts_em("ads"), [])
        (linha,) = self.log()
        self.assertEqual(linha["resultado"], "erro")
        self.assertIn("campaign_id", linha["ids"])
        # nenhuma chamada destrutiva
        self.assertTrue(all("status" not in p["params"] or p["params"]["status"] == "PAUSED" for p in self.api.posts))

    def test_nasceu_ativo_e_apontado_como_problema(self):
        self.api.nasce_ativo = True
        codigo, texto = self.rodar("--confirmar")
        self.assertEqual(codigo, 1)
        self.assertIn("Não consegui confirmar o status PAUSADO", texto)
        self.assertNotIn("python3 meta_acoes.py ativar", texto)

    def test_interesse_inexistente_recusa_sem_criar_nada(self):
        self.spec["publico"]["interesses"] = ["interesse que nao existe"]
        codigo, texto = self.rodar("--confirmar")
        self.assertEqual(codigo, 1)
        self.assertIn("não tem o interesse", texto)
        self.assertEqual(self.api.posts, [])

    def test_extras_sao_mesclados(self):
        self.spec["conjunto_extra"] = {"is_adset_budget_sharing_enabled": False}
        self.spec["targeting_extra"] = {"targeting_automation": {"advantage_audience": 0}}
        self.rodar("--confirmar")
        (conj,) = self.posts_em("adsets")
        self.assertIs(conj["params"]["is_adset_budget_sharing_enabled"], False)
        self.assertEqual(conj["params"]["targeting"]["targeting_automation"], {"advantage_audience": 0})


class TestSeguranca(Base):
    def test_extra_com_status_e_recusado_antes_de_criar_qualquer_coisa(self):
        casos = [
            ("campanha_extra", {"status": "ACTIVE"}), ("conjunto_extra", {"status": "ACTIVE"}),
            ("conjunto_extra", {"daily_budget": "300000"}), ("campanha_extra", {"daily_budget": "1"}),
            ("targeting_extra", {"geo_locations": {"countries": ["US"]}}),
            ("criativo_extra", {"object_story_spec": {"page_id": "1"}}),
            ("criativo_extra", {"instagram_actor_id": "1"}),
        ]
        for chave, valor in casos:
            self.spec = copy.deepcopy(meta_publicar.EXEMPLO)
            self.spec["criativo"]["arquivo"] = "criativo.png"
            self.spec[chave] = valor
            self.api.posts = []
            codigo, texto = self.rodar("--confirmar")
            self.assertEqual(codigo, 1, (chave, valor))
            self.assertIn("não pode trazer", texto)
            self.assertEqual(self.api.posts, [])

    def test_extra_permitido_aparece_no_resumo(self):
        self.spec["conjunto_extra"] = {"is_adset_budget_sharing_enabled": False}
        _, texto = self.rodar()
        self.assertIn("is_adset_budget_sharing_enabled", texto)

    def test_timeout_ao_criar_campanha_avisa_que_pode_ter_sido_criada(self):
        original = self.api.post

        def post(caminho, params, campo_arquivo=None, arquivo=None):
            if caminho.endswith("/campaigns"):
                raise meta_acoes.SemResposta("Sem resposta da Meta: timed out")
            return original(caminho, params, campo_arquivo, arquivo)

        self.api.post = post
        codigo, texto = self.rodar("--confirmar")
        self.assertEqual(codigo, 1)
        self.assertIn("PODE ter sido criada", texto)
        self.assertIn(self.spec["nome"], texto)

    def test_resposta_perdida_na_publicacao_grava_incerto(self):
        original = self.api.post

        def post(caminho, params, campo_arquivo=None, arquivo=None):
            if caminho.endswith("/campaigns"):
                raise meta_acoes.SemResposta("Sem resposta da Meta: timed out")
            return original(caminho, params, campo_arquivo, arquivo)

        self.api.post = post
        self.rodar("--confirmar")
        self.assertEqual(self.log()[-1]["resultado"], "incerto")

    def test_upload_sem_resposta_nao_manda_procurar_nome_vazio(self):
        def post(caminho, params, campo_arquivo=None, arquivo=None):
            raise meta_acoes.SemResposta("Sem resposta da Meta: timed out")

        self.api.post = post
        _, texto = self.rodar("--confirmar")
        self.assertIn("biblioteca de mídia", texto)
        self.assertNotIn('nome ""', texto)

    def test_interesse_aproximado_e_marcado_no_resumo(self):
        self.api.interesses["empreendedorismo"] = {"id": "6009", "name": "Empreendedorismo social"}
        self.spec["publico"]["interesses"] = ["Empreendedorismo"]
        codigo, texto = self.rodar()
        self.assertIn("APROXIMADO", texto)
        codigo, texto = self.rodar("--confirmar")
        self.assertEqual(codigo, 1)
        self.assertEqual(self.api.posts, [])
        codigo, texto = self.rodar("--confirmar", "--aceitar-aproximado")
        self.assertEqual(codigo, 0)
        self.assertTrue(self.posts_em("campaigns"))


class TestValidacao(Base):
    def test_interesses_como_texto_unico_e_recusado(self):
        self.spec["publico"]["interesses"] = "Marketing digital"
        codigo, texto = self.rodar()
        self.assertEqual(codigo, 1)
        self.assertIn("lista de textos", texto)

    def test_publico_ou_criativo_que_nao_e_objeto_da_mensagem(self):
        for bloco in ("publico", "criativo"):
            self.spec = copy.deepcopy(meta_publicar.EXEMPLO)
            self.spec["criativo"]["arquivo"] = "criativo.png"
            self.spec[bloco] = "texto solto"
            codigo, texto = self.rodar()
            self.assertEqual(codigo, 1)
            self.assertIn("precisa ser um objeto JSON", texto)

    def _recusa(self, mutacao, trecho):
        mutacao(self.spec)
        codigo, texto = self.rodar("--confirmar")
        self.assertEqual(codigo, 1, texto)
        self.assertIn(trecho, texto)
        self.assertEqual(self.api.posts, [])

    def test_objetivo_invalido(self):
        self._recusa(lambda s: s.update(objetivo="alcance"), "não suportado")

    def test_arquivo_inexistente(self):
        self._recusa(lambda s: s["criativo"].update(arquivo="nao-existe.png"), "Arquivo não encontrado")

    def test_formato_nao_aceito(self):
        (self.tmp / "doc.pdf").write_bytes(b"x")
        self._recusa(lambda s: s["criativo"].update(arquivo="doc.pdf"), "não aceito")

    def test_video_sem_capa(self):
        def mut(s):
            s["criativo"].update(tipo="video", arquivo="video.mp4")
            s["criativo"].pop("thumbnail", None)
        self._recusa(mut, "criativo.thumbnail")

    def test_link_sem_https(self):
        self._recusa(lambda s: s["criativo"].update(link="seusite.com"), "http://")

    def test_orcamento_ambiguo_ou_zero(self):
        self._recusa(lambda s: s.update(orcamento_diario="0"), "maior que zero")

    def test_idade_invertida(self):
        self._recusa(lambda s: s["publico"].update(idade_min=60, idade_max=30), "idade_min")

    def test_pais_invalido(self):
        self._recusa(lambda s: s["publico"].update(paises=["Brasil"]), "2 letras")

    def test_arquivo_acima_do_teto(self):
        antigo = meta_publicar.LIMITE_IMAGEM_MB
        meta_publicar.LIMITE_IMAGEM_MB = 0
        try:
            (self.tmp / "criativo.png").write_bytes(b"x" * 10)
            self._recusa(lambda s: None, "ZX_TPA_MAX_IMAGEM_MB")
        finally:
            meta_publicar.LIMITE_IMAGEM_MB = antigo

    def test_spec_inexistente(self):
        saida = []
        codigo = meta_publicar.main([str(self.tmp / "nada.json")], api=self.api, paths=self.paths, out=saida.append)
        self.assertEqual(codigo, 1)
        self.assertIn("--exemplo", "\n".join(saida))


class TestMultiProjeto(Base):
    def test_conta_vem_do_projeto_nao_do_arquivo(self):
        self.spec["conta"] = "act_999"  # campo ignorado: a conta é do projeto
        self.rodar("--confirmar")
        self.assertTrue(all(p["caminho"].startswith(CONTA) for p in self.api.posts))

    def test_log_no_projeto_ativo(self):
        tpa_paths.create_project("cliente-x", self.tmp / "base", activate=False, port_free=lambda p: True)
        proj = tpa_paths.active_paths(env={"OPERACAO_IA_HOME": str(self.tmp / "base"), "TPA_PROJECT": "cliente-x"},
                                      file=str(self.tmp / "nao-instalado" / "x.py"))
        proj.meta_env.write_text(self.paths.meta_env.read_text(encoding="utf-8"), encoding="utf-8")
        arq = self.tmp / "campanha.json"
        arq.write_text(json.dumps(self.spec), encoding="utf-8")
        saida = []
        meta_publicar.main([str(arq), "--confirmar"], api=self.api, paths=proj, out=saida.append, sleep=lambda s: None)
        self.assertTrue((Path(proj.logs) / meta_acoes.LOG_NAME).exists())
        self.assertFalse((Path(self.paths.logs) / meta_acoes.LOG_NAME).exists())


class TestTextoDoAluno(unittest.TestCase):
    def test_fonte_nao_cita_colaborador_nem_so_mac(self):
        texto = (REPO / "scripts" / "meta_publicar.py").read_text(encoding="utf-8").lower()
        for proibido in ("seu mac",):
            self.assertNotIn(proibido, texto)


if __name__ == "__main__":
    unittest.main()
