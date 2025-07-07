import os
import hashlib
from datetime import datetime
import requests
from bs4 import BeautifulSoup
import telegram
import time
import schedule
import json

# Configuração
TELEGRAM_TOKEN = "7802497378:AAF4KQZqPCuCYPp2R-QWse2SOtWl8iCiE3k"
CHAT_ID = "891690046"
SITES_IMOBILIARIAS = [
    "https://www.criativaimoveis.com.br/imovel/alugar",
    "https://sinuelo.net/",
    "https://sinuelo.net/busca?finalidade=Aluguel&tipo=Apartamento%2CCasa&cidade=Novo+Hamburgo%2CNOVO+HAMBURGO",
    "https://www.houseimoveis.com.br/imoveis/aluguel/novo-hamburgo/-/-/apartamento+apartamento+casa+casa+casa-em-condominio+casa-em-condominio?filtros&min=120&max=15000&ordem=desc-valor&pagination=1"
]

# Inicializar bot do Telegram
bot = telegram.Bot(token=TELEGRAM_TOKEN)

# Arquivo para salvar hashes das páginas monitoradas
HASHES_ARQUIVO = 'paginas_hashes.json'
LOGS_ARQUIVO = 'notificacoes.txt'  # Definindo a variável LOGS_ARQUIVO aqui

def main():
    print("Bot de monitoramento de imóveis iniciado!")

    # Enviar notificação de inicialização
    enviar_notificacao("🏠 *Bot de Monitoramento de Imóveis Iniciado!*\n\nO bot está monitorando os seguintes sites:\n" +
                       "\n".join(f"- {site}" for site in SITES_IMOBILIARIAS))

# Função para enviar notificações via Telegram
def enviar_notificacao(mensagem):
    try:
        # Salvar em arquivo para backup
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(LOGS_ARQUIVO, 'a', encoding='utf-8') as f:
            f.write(f"[{timestamp}] {mensagem}\n\n")

        # Enviar para o Telegram
        bot.send_message(
            chat_id=CHAT_ID,
            text=mensagem,
            parse_mode="Markdown"  # Opcional: permite formatação básica
        )
        print(f"Notificação enviada para o Telegram: {mensagem[:50]}...")

    except Exception as e:
        print(f"Erro ao enviar notificação para o Telegram: {str(e)}")
        print("A mensagem foi salva apenas no arquivo de logs.")

# Carregar hashes das páginas anteriores
def carregar_hashes():
    if os.path.exists(HASHES_ARQUIVO):
        with open(HASHES_ARQUIVO, 'r') as f:
            return json.load(f)
    return {}

# Salvar hashes atuais
def salvar_hashes(hashes):
    with open(HASHES_ARQUIVO, 'w') as f:
        json.dump(hashes, f)

# Função para limpar o HTML removendo partes não relevantes
def limpar_html(html):
    soup = BeautifulSoup(html, 'html.parser')

    # Remover scripts, estilos e comentários
    for tag in soup(['script', 'style', 'meta', 'link', 'noscript']):
        tag.decompose()

    # Remover comentários HTML
    for comment in soup.find_all(string=lambda text: isinstance(text, str) and '<!--' in text):
        comment.extract()

    return str(soup)

# Extrair seções potenciais de listagens
def extrair_secoes_listagem(html):
    soup = BeautifulSoup(html, 'html.parser')

    # Procurar seções que provavelmente são listagens de imóveis
    # Estratégia 1: Procurar por contêineres com vários elementos similares
    secoes = []

    # Procurar padrões comuns em sites imobiliários
    padrao_classes = ['listing', 'results', 'properties', 'imoveis', 'cards', 'grid', 'lista']
    for classe in padrao_classes:
        containers = soup.select(f"div[class*='{classe}'], ul[class*='{classe}'], section[class*='{classe}']")
        secoes.extend(containers)

    # Se nada for encontrado, procurar divs que contêm múltiplos elementos com estrutura similar
    if not secoes:
        candidatos = soup.select('div, section, ul')
        for candidato in candidatos:
            # Verificar se tem vários filhos similares (potencial listagem)
            filhos = candidato.find_all(['article', 'div', 'li'], recursive=False)
            if len(filhos) >= 3:  # Pelo menos 3 itens similares
                secoes.append(candidato)

    # Se ainda não encontrou nada, procurar por artigos ou cards
    if not secoes:
        secoes = soup.select('article, div.card, div[class*="card"], li[class*="item"]')

    return secoes

# Função principal para verificar mudanças nas seções de listagens
def verificar_mudancas():
    hashes_anteriores = carregar_hashes()
    hashes_atuais = {}
    mudancas_detectadas = False

    for site in SITES_IMOBILIARIAS:
        print(f"Verificando: {site}")

        try:
            # Fazer requisição HTTP com cabeçalhos de navegador
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml",
                "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7"
            }
            response = requests.get(site, headers=headers, timeout=30)

            if response.status_code == 200:
                # Limpar o HTML
                html_limpo = limpar_html(response.text)

                # Extrair seções que parecem ser listagens
                secoes = extrair_secoes_listagem(html_limpo)

                # Se não encontrou seções específicas, usar a página toda
                if not secoes:
                    print(f"Nenhuma seção de listagem identificada em {site}. Usando página completa.")
                    secoes = [BeautifulSoup(html_limpo, 'html.parser')]

                print(f"Encontradas {len(secoes)} possíveis seções de listagem em {site}")

                # Para cada seção, calcular um hash
                hashes_secoes = []
                for i, secao in enumerate(secoes):
                    # Pegar apenas o texto e links, ignorando formatação
                    conteudo = []
                    for elem in secao.find_all(['a', 'h1', 'h2', 'h3', 'h4', 'p', 'span']):
                        if elem.name == 'a' and elem.get('href'):
                            conteudo.append(f"{elem.text.strip()}:{elem.get('href')}")
                        else:
                            conteudo.append(elem.text.strip())

                    # Filtrar strings vazias
                    conteudo = [c for c in conteudo if c]

                    if conteudo:
                        # Calcular hash do conteúdo
                        conteudo_str = '|'.join(conteudo)
                        hash_secao = hashlib.md5(conteudo_str.encode('utf-8')).hexdigest()
                        hashes_secoes.append(hash_secao)

                # Verificar se há mudanças
                site_key = site.split('/')[2]  # Ex: www.imobiliaria1.com.br

                if site_key in hashes_anteriores:
                    # Comparar hashes anteriores com atuais
                    hashes_antigos = set(hashes_anteriores[site_key])
                    hashes_novos = set(hashes_secoes)

                    # Verificar se há novos hashes (novas seções ou seções alteradas)
                    novos = hashes_novos - hashes_antigos

                    if novos:
                        mudancas_detectadas = True
                        num_novos = len(novos)
                        mensagem = f"🏠 NOVOS IMÓVEIS DETECTADOS!\n\n"
                        mensagem += f"Detectei mudanças em {num_novos} seção(ões) em:\n"
                        mensagem += f"{site_key} - {site}\n\n"
                        mensagem += "Acesse o site para ver os novos imóveis!"
                        enviar_notificacao(mensagem)

                # Armazenar hashes atuais para próxima verificação
                hashes_atuais[site_key] = hashes_secoes

            else:
                print(f"Erro ao acessar {site}: Status code {response.status_code}")

        except Exception as e:
            print(f"Erro ao processar {site}: {str(e)}")

    # Salvar os hashes atuais
    salvar_hashes(hashes_atuais)

    return mudancas_detectadas

# Loop principal
def main():
    print("Bot de monitoramento de imóveis iniciado!")
    print("Este bot detecta mudanças em listagens de imóveis sem precisar de seletores CSS específicos.")

    # Se for a primeira execução, apenas salvar os hashes iniciais
    if not os.path.exists(HASHES_ARQUIVO):
        print("Primeira execução: salvando estado inicial dos sites...")
        verificar_mudancas()
        print("Estado inicial salvo. O bot detectará mudanças a partir da próxima verificação.")

    intervalo_minutos = 30

    while True:
        print(f"\nVerificando sites em {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}...")
        verificar_mudancas()
        print(f"Próxima verificação em {intervalo_minutos} minutos.")
        time.sleep(intervalo_minutos * 60)  # Converter para segundos

if __name__ == "__main__":
    main()