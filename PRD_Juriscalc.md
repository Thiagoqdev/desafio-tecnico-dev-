# PRD — Juriscalc

**Documento de Requisitos de Produto (Product Requirement Document)**
**Projeto:** Juriscalc — Plataforma de Cálculos Jurídicos
**Módulo inicial:** Atualização e Correção Monetária
**Versão:** 1.0
**Status:** Blueprint de desenvolvimento

---

## Sumário

1. [Visão Geral](#1-visão-geral)
2. [Suposições Adotadas](#2-suposições-adotadas)
3. [Escopo](#3-escopo)
4. [Requisitos Funcionais](#4-requisitos-funcionais)
5. [Requisitos Não Funcionais](#5-requisitos-não-funcionais)
6. [Regras de Negócio da Legislação](#6-regras-de-negócio-da-legislação)
7. [Arquitetura Técnica](#7-arquitetura-técnica)
8. [Modelos de Dados](#8-modelos-de-dados)
9. [Fluxo de Cálculo Determinístico](#9-fluxo-de-cálculo-determinístico)
10. [Fluxo de Interpretação por LLM](#10-fluxo-de-interpretação-por-llm)
11. [Interface](#11-interface)
12. [Plano de Desenvolvimento por Sprints](#12-plano-de-desenvolvimento-por-sprints)
13. [Critérios de Aceitação](#13-critérios-de-aceitação)
14. [Riscos](#14-riscos)
15. [Glossário](#15-glossário)

---

## 1. Visão Geral

O **Juriscalc** é uma plataforma web modular de cálculos jurídicos. Seu objetivo é oferecer a profissionais do direito uma ferramenta confiável, transparente e auditável para elaboração de cálculos de atualização monetária, juros e demais verbas processuais.

O produto nasce modular: cada módulo cobre uma família de cálculos. O **primeiro módulo** entregue é o de **Atualização e Correção Monetária**.

O **diferencial central** do Juriscalc é a **interpretação de sentenças por LLM**: o usuário cola o texto de uma sentença, um grafo LangGraph interpreta o conteúdo e **preenche automaticamente o formulário** do front-end. O usuário **revisa** os dados preenchidos, ajusta o que for necessário e só então dispara o cálculo. O cálculo em si é **sempre determinístico** e executado pelo back-end.

### 1.1 Princípio Arquitetural Inegociável

> **A interpretação (LLM) e o cálculo (back-end) são estritamente separados.**
> O grafo LangGraph **somente extrai e estrutura** dados da sentença e preenche o formulário. O grafo **nunca** executa o cálculo. O cálculo é sempre disparado pelo usuário após revisão humana e processado pelo back-end determinístico.

### 1.2 Objetivos do Produto

- Reduzir o tempo de elaboração de cálculos de atualização monetária.
- Eliminar erros de transcrição manual de dados de sentenças.
- Garantir conformidade com a legislação vigente sobre índices e juros (EC 113/2021, EC 136/2025).
- Produzir memória de cálculo detalhada, auditável e exportável.
- Manter rastreabilidade total: todo número exibido deve ser explicável.

### 1.3 Público-Alvo

Advogados, contadores judiciais, assessores jurídicos, peritos e servidores de varas e tribunais.

---

## 2. Suposições Adotadas

Em conformidade com a regra de explicitar suposições quando um requisito for ambíguo ou incompleto, registram-se as seguintes premissas:

| # | Tema | Suposição adotada |
|---|------|-------------------|
| S1 | Autenticação | Assume-se uso do sistema de autenticação nativo do Django (`django.contrib.auth`). O escopo de papéis/permissões avançadas fica fora do módulo inicial. |
| S2 | Provedor de LLM | A camada de LLM é abstraída por LangChain; o provedor concreto (ex.: OpenAI, Anthropic, modelo local) é configurável via variável de ambiente. Nenhum provedor específico é hardcoded. |
| S3 | Período de cobertura de índices | Para datas anteriores a 1984 não há regra na tabela de negócio; o sistema rejeita termos iniciais anteriores a 01/1984 com mensagem clara, em vez de inventar índice. |
| S4 | "Tabela da Justiça Federal" | Interpretada como a tabela de fatores de atualização do CJF/Manual de Cálculos da Justiça Federal, disponibilizada como índice selecionável manualmente e carregada via dados parametrizáveis/cache. |
| S5 | Honorários | O percentual de honorários incide sobre o valor atualizado acrescido de juros, salvo configuração em contrário no próprio formulário. Base de incidência é exibida na memória de cálculo. |
| S6 | "IPCA + 2% a.a. limitado à SELIC" (EC 136/2025) | Interpretado como: aplica-se IPCA acrescido de 2% ao ano; caso o resultado acumulado supere a variação da SELIC no mesmo período, aplica-se o teto da SELIC. A comparação é feita período a período conforme parametrização da tabela de vigências. |
| S7 | Arredondamento | Todos os cálculos monetários usam `Decimal` com arredondamento `ROUND_HALF_EVEN` (bancário) e quantização a 2 casas decimais no valor final; valores intermediários preservam precisão estendida. |
| S8 | Fonte dos índices | INPC e IPCA-E via API do IBGE; SELIC, IGP-M e séries auxiliares via API do Banco Central (SGS). Todos com cache local persistido. |
| S9 | Internacionalização | Interface 100% em pt-BR; o código (identificadores, comentários) em inglês. Locale do Django configurado para `pt-br` e timezone `America/Sao_Paulo`. |
| S10 | Multitenancy | O módulo inicial assume cálculos vinculados a um usuário autenticado, sem isolamento multiempresa. |
| S11 | RPV/Precatório emitido | Quando o usuário marca a opção "RPV/Precatório emitido" e informa a data de emissão, a correção monetária **a partir dessa data** passa a ser IPCA + 2% a.a. limitado à SELIC (mesmo regime do `ipca_plus_capped` da EC 136/2025), independentemente do período. Quando a opção **não** está marcada, mantém-se a atualização pela SELIC conforme a tabela de vigências vigente. A data de emissão deve ser igual ou posterior ao termo inicial e anterior ou igual ao termo final; caso esteja fora desse intervalo, o sistema exibe mensagem clara e não calcula. |

---

## 3. Escopo

### 3.1 Dentro do Escopo (módulo inicial)

- Cadastro e autenticação de usuários (Django auth nativo).
- Formulário de cálculo de Atualização e Correção Monetária.
- Seleção manual de índice **ou** aplicação automática da legislação.
- Campo de juros de mora.
- Campo de honorários advocatícios (percentual configurável).
- Parcela única **ou** múltiplas parcelas (iguais ou distintas).
- Opção "RPV/Precatório emitido" com data de emissão, alterando o regime de correção a partir dessa data.
- Cálculo determinístico no back-end.
- Memória de cálculo detalhada.
- Interpretação de sentença por LLM (LangGraph) com preenchimento do formulário.
- Revisão humana obrigatória antes do cálculo.
- Integração com APIs públicas (IBGE, BCB/SGS) e cache local de índices.
- Tabela de vigências parametrizável em banco.
- Testes automatizados.

### 3.2 Fora do Escopo (módulo inicial)

- Outros módulos de cálculo (trabalhista, contratual, liquidação de sentença complexa).
- Geração de petições.
- Assinatura digital / integração com PJe ou e-SAJ.
- Multiempresa / multitenancy com isolamento de dados.
- Aplicativo mobile nativo.
- Pagamentos/assinaturas (billing).
- Treinamento ou fine-tuning de modelos de LLM (usa-se apenas inferência via API).

---

## 4. Requisitos Funcionais

| ID | Requisito |
|----|-----------|
| RF01 | O sistema deve permitir informar um **valor base** a atualizar, com **termo inicial** e **termo final**. |
| RF02 | O sistema deve permitir **seleção manual de índice** (INPC, IPCA-E, IGP-M, SELIC, Tabela da Justiça Federal). |
| RF03 | O sistema deve permitir o **modo de aplicação automática da legislação**, aplicando os índices e juros por período conforme a tabela de vigências. |
| RF04 | O sistema deve oferecer **campo dedicado para juros de mora**. |
| RF05 | O sistema deve oferecer **campo para honorários advocatícios** com **percentual configurável**. |
| RF06 | O sistema deve permitir escolher entre **parcela única** ou **múltiplas parcelas**. |
| RF07 | Em múltiplas parcelas, o sistema deve permitir definir **quantas parcelas** adicionar. |
| RF08 | Em múltiplas parcelas, o sistema deve permitir indicar se as demais têm **valor igual ao da primeira** ou **valores distintos** (informados individualmente). |
| RF09 | O sistema deve produzir uma **memória de cálculo detalhada** no resultado, explicando cada etapa, índice aplicado, fator e período. |
| RF10 | O sistema deve permitir colar o **texto de uma sentença** e acionar a **interpretação por LLM**. |
| RF11 | A LLM deve **preencher o formulário** com os dados extraídos da sentença, sem executar cálculo. |
| RF12 | O usuário deve **revisar e editar** os dados preenchidos antes de calcular. |
| RF13 | O **cálculo só pode ser disparado pelo usuário** após a revisão. |
| RF14 | O sistema deve buscar índices via **APIs públicas** e manter **cache local**. |
| RF15 | O sistema deve permitir **persistir e recuperar** cálculos realizados pelo usuário. |
| RF16 | O sistema deve exibir **mensagens claras** quando dados forem inválidos ou faltarem índices para o período. |
| RF17 | A tabela de vigências (índices/juros por período) deve ser **parametrizável em banco**, nunca hardcoded. |
| RF18 | O sistema deve oferecer um **checkbox "RPV/Precatório emitido"**. Quando marcado, deve exibir um campo para informar a **data de emissão**. |
| RF19 | Quando o checkbox "RPV/Precatório emitido" estiver marcado, a correção monetária **a partir da data de emissão** deve ser **IPCA + 2% a.a. limitado à SELIC**; quando **não** marcado, a atualização deve seguir pela **SELIC** conforme a tabela de vigências. |

---

## 5. Requisitos Não Funcionais

| ID | Requisito |
|----|-----------|
| RNF01 | **Código em inglês**; identificadores, nomes de funções, classes e comentários em inglês. |
| RNF02 | **Interface 100% em português brasileiro**, com acentuação correta. |
| RNF03 | Aderência à **PEP 8**; código simples e direto. |
| RNF04 | Uso de **aspas simples** sempre que possível. |
| RNF05 | **SQLite padrão do Django** como banco de dados. |
| RNF06 | Toda model deve conter os campos **`created_at`** e **`updated_at`**. |
| RNF07 | **Testes automatizados** obrigatórios (unitários e de integração). |
| RNF08 | Preferência por **Class Based Views**, classes, funções e recursos nativos do Django. |
| RNF09 | **Signals**, quando usados, residem em **`signals.py`** dentro da app correspondente. |
| RNF10 | Valores monetários usam **`Decimal`**, nunca `float`. |
| RNF11 | Todo o design respeita rigorosamente **`@design_system/design-system.html`**; nenhum estilo fora do design system. |
| RNF12 | **Determinismo do cálculo**: a mesma entrada produz sempre a mesma saída. |
| RNF13 | **Separação estrita** entre interpretação (LLM) e cálculo (back-end). |
| RNF14 | **Auditabilidade**: toda saída numérica deve ser explicável pela memória de cálculo. |
| RNF15 | **Resiliência de índices**: indisponibilidade de API externa não pode quebrar cálculos cujos índices já estejam em cache. |
| RNF16 | Locale `pt-br`, timezone `America/Sao_Paulo`. |

---

## 6. Regras de Negócio da Legislação

> **Regra arquitetural:** Estas tabelas **devem** ser implementadas como **dados parametrizáveis em banco** (tabela de vigências). **Nunca** hardcoded no código de cálculo.

### 6.1 Correção Monetária por Período

| Período | Índice aplicável | Fundamento |
|---------|------------------|-----------|
| 1984 a 1991 | INPC | — |
| 1992 a 08/12/2021 | IPCA-E | — |
| 09/12/2021 a 09/2025 | SELIC (taxa única) | EC 113/2021 |
| 10/2025 em diante | IPCA + 2% a.a., limitado à SELIC | EC 136/2025 |

### 6.2 Juros Moratórios por Período

| Período | Juros de mora | Fundamento |
|---------|---------------|-----------|
| Até 06/2009 | 1% a.m. | — |
| 07/2009 a 08/12/2021 | 0,5% a.m. | — |
| 09/12/2021 em diante | SELIC ou IPCA+2% conforme EC vigente | EC 113/2021 e EC 136/2025 |

### 6.3 Regra de Não Cumulação

> A partir de **09/12/2021**, a **SELIC unifica correção monetária e juros**. Não há cumulação de correção e juros nesse período: aplica-se exclusivamente a SELIC (ou IPCA+2% limitado à SELIC, conforme EC vigente). O motor de cálculo deve impedir a dupla incidência nesses intervalos.

### 6.4 Regra de RPV/Precatório Emitido

> Quando o usuário marca a opção **"RPV/Precatório emitido"** e informa a **data de emissão**, a correção monetária **a partir dessa data** passa a seguir o regime **IPCA + 2% a.a. limitado à SELIC** (mesma mecânica do modo `ipca_plus_capped`, conforme S6), **sobrepondo-se** à regra de correção que a tabela de vigências aplicaria naquele período.
>
> Quando a opção **não** está marcada, a correção segue normalmente pela **SELIC** (conforme a tabela de vigências vigente para o período), sem qualquer alteração.
>
> A data de emissão divide o cálculo em dois trechos: **antes da emissão**, aplica-se a regra de correção da tabela de vigências; **a partir da emissão (inclusive)**, aplica-se IPCA + 2% limitado à SELIC. A não cumulação da Seção 6.3 continua válida em ambos os trechos.

| Condição | Correção a partir da data de emissão |
|----------|--------------------------------------|
| Checkbox "RPV/Precatório emitido" **marcado** | IPCA + 2% a.a., limitado à SELIC |
| Checkbox **não** marcado | SELIC (conforme tabela de vigências) |

---

## 7. Arquitetura Técnica

### 7.1 Stack

| Camada | Tecnologia |
|--------|-----------|
| Linguagem | Python |
| Framework web | Django |
| Orquestração de LLM | LangChain / LangGraph |
| Banco de dados | SQLite (padrão do Django) |
| Fontes de índices | API IBGE (INPC, IPCA-E), API BCB/SGS (SELIC, IGP-M, séries auxiliares) |
| Front-end | Templates Django + design system (`design-system.html`) |
| Testes | `django.test` / `pytest-django` (opcional, ver abaixo) |

> **Tecnologias opcionais (declaradas explicitamente):** `pytest-django` pode ser adotado como runner de testes por conveniência; caso não, usa-se o runner nativo do Django. `requests`/`httpx` para chamadas HTTP às APIs públicas é considerado dependência de infraestrutura padrão. Nenhuma outra tecnologia fora da stack definida é introduzida.

### 7.2 Apps Django

A solução é dividida em apps coesas e de responsabilidade única:

| App | Responsabilidade |
|-----|------------------|
| **`accounts`** | Autenticação e perfil de usuário (sobre `django.contrib.auth`). |
| **`indices`** | Modelagem, busca e cache dos índices econômicos (INPC, IPCA-E, IGP-M, SELIC, Tabela JF). Clientes das APIs públicas. |
| **`legislation`** | Tabela de vigências parametrizável: regras de correção e juros por período. Resolve qual índice/juros se aplica a cada intervalo. |
| **`calculations`** | Motor de cálculo determinístico, modelos de cálculo e parcelas, memória de cálculo. |
| **`interpreter`** | Grafo LangGraph de interpretação de sentenças. Extrai dados e devolve estrutura para preencher o formulário. **Nunca calcula.** |
| **`core`** | Base abstrata (`TimeStampedModel`), utilidades comuns, configurações compartilhadas. |

### 7.3 Separação Interpretação × Cálculo

```
┌──────────────────────────────────────────────────────────────────┐
│                          FRONT-END                                │
│                                                                    │
│  [Texto da sentença] ──► (POST) ──► interpreter                   │
│                                         │                          │
│                                         ▼                          │
│                            LangGraph (extrai/estrutura)            │
│                                         │                          │
│                                         ▼                          │
│   Formulário preenchido ◄───────── dados estruturados             │
│                                                                    │
│  [Revisão humana / edição]                                        │
│            │                                                       │
│            ▼ (usuário dispara)                                    │
│       (POST) ──► calculations  ──►  Motor determinístico          │
│                                         │                          │
│                                         ▼                          │
│                              Resultado + memória de cálculo        │
└──────────────────────────────────────────────────────────────────┘
```

A app `interpreter` **não importa** o motor de cálculo da app `calculations`. O único acoplamento permitido é o formato de dados do formulário (DTO/serializer), garantindo que a LLM jamais dispare cálculo.

---

## 8. Modelos de Dados

Todas as models herdam de `core.models.TimeStampedModel`, que provê `created_at` e `updated_at`.

### 8.1 `core`

```python
class TimeStampedModel(models.Model):
    'Abstract base model providing creation and update timestamps.'
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
```

### 8.2 `indices`

| Model | Campos principais |
|-------|-------------------|
| `IndexType` | `name` (ex.: 'INPC'), `code`, `source` ('IBGE'/'BCB'/'CJF'), `sgs_series_id` (nullable), `description` |
| `IndexValue` | `index_type` (FK), `reference_date`, `value` (`DecimalField`), `accumulated_factor` (`DecimalField`, nullable), `fetched_at` |

`IndexValue` constitui o **cache local**. Constraint de unicidade em (`index_type`, `reference_date`).

### 8.3 `legislation`

| Model | Campos principais |
|-------|-------------------|
| `CorrectionRule` | `start_date`, `end_date` (nullable = vigente), `index_type` (FK), `mode` ('single_index'/'ipca_plus_capped'), `extra_rate` (`DecimalField`, ex.: 2% a.a.), `legal_basis` (ex.: 'EC 113/2021') |
| `InterestRule` | `start_date`, `end_date` (nullable), `monthly_rate` (`DecimalField`, nullable), `uses_selic` (bool), `mode`, `legal_basis` |
| `UnificationRule` | `start_date`, `end_date` (nullable), `unifies_correction_and_interest` (bool), `legal_basis` |

Essas três tabelas materializam a Seção 6 como **dados parametrizáveis**, carregados via data migration/fixtures editáveis.

### 8.4 `calculations`

| Model | Campos principais |
|-------|-------------------|
| `Calculation` | `user` (FK), `base_value` (`DecimalField`), `start_term` (date), `end_term` (date), `index_selection_mode` ('manual'/'auto'), `manual_index` (FK nullable), `interest_enabled` (bool), `attorney_fee_percent` (`DecimalField`), `installment_mode` ('single'/'multiple'), `rpv_issued` (bool), `rpv_issue_date` (date, nullable), `result_total` (`DecimalField`, nullable), `status` ('draft'/'computed') |
| `Installment` | `calculation` (FK), `order`, `value` (`DecimalField`), `same_as_first` (bool) |
| `CalculationStep` | `calculation` (FK), `order`, `description` (text), `period_start`, `period_end`, `applied_index`, `factor` (`DecimalField`), `interest_amount` (`DecimalField`), `subtotal` (`DecimalField`) |

`CalculationStep` é a **memória de cálculo** persistida e exibível.

### 8.5 `interpreter`

| Model | Campos principais |
|-------|-------------------|
| `SentenceInterpretation` | `user` (FK), `source_text` (text), `extracted_payload` (`JSONField`), `model_used`, `confidence_notes` (text), `status` ('extracted'/'reviewed'/'discarded') |

Observação: `SentenceInterpretation` armazena apenas o **resultado da extração** (dados para o formulário). Não há referência a resultado de cálculo aqui — reforçando a separação.

---

## 9. Fluxo de Cálculo Determinístico

O motor reside em `calculations.services` (classe `CalculationEngine`) e é puramente determinístico.

### 9.1 Etapas

1. **Validação de entrada**: valida termos, valor base > 0, percentuais válidos, parcelas consistentes; rejeita termo inicial anterior a 01/1984 (S3). Quando `rpv_issued` for verdadeiro, valida que `rpv_issue_date` foi informada e está dentro do intervalo [termo inicial, termo final] (S11).
2. **Expansão de parcelas**: monta a lista de parcelas (única, iguais ou distintas) com seus respectivos valores e termos iniciais.
3. **Resolução de regras por período** (modo automático): para cada subintervalo entre `start_term` e `end_term`, consulta `legislation` para obter regra de correção, regra de juros e regra de unificação aplicáveis.
4. **Aplicação da regra de RPV/Precatório** (Seção 6.4, S11): quando `rpv_issued` for verdadeiro, insere um ponto de corte na `rpv_issue_date`; para todos os subintervalos a partir dessa data (inclusive), a regra de correção é **substituída** por IPCA + 2% limitado à SELIC (`ipca_plus_capped`), sobrepondo-se à regra da tabela de vigências. Quando falso, mantém-se a SELIC conforme a tabela.
5. **Obtenção de índices**: para cada subintervalo, busca fatores em `indices` (cache local; se ausente, dispara o cliente da API e persiste).
6. **Correção monetária**: aplica o fator de correção a cada parcela por subintervalo, usando `Decimal`.
7. **Juros de mora**: aplica juros conforme regra do período, **respeitando a não cumulação** a partir de 09/12/2021 (Seção 6.3).
8. **Honorários**: aplica o percentual configurado sobre a base definida (S5).
9. **Consolidação**: soma parcelas e produz `result_total`.
10. **Memória de cálculo**: cada operação gera um `CalculationStep` descritivo (período, índice, fator, juros, subtotal), explicitando o trecho afetado pela emissão de RPV/Precatório quando aplicável.
11. **Persistência**: salva `Calculation` com `status='computed'` e seus `CalculationStep`.

### 9.2 Garantias

- Uso exclusivo de `Decimal` (RNF10), arredondamento `ROUND_HALF_EVEN` (S7).
- Nenhuma dependência da app `interpreter`.
- Idempotência: recalcular a mesma entrada produz a mesma saída (RNF12).

---

## 10. Fluxo de Interpretação por LLM

A app `interpreter` orquestra um grafo LangGraph cujo único papel é **extrair e estruturar** dados.

### 10.1 Nós do Grafo (LangGraph)

| Nó | Responsabilidade |
|----|------------------|
| `ingest` | Recebe o texto bruto da sentença e normaliza (remove ruído, limita tamanho). |
| `extract` | Invoca a LLM (via LangChain) para extrair: valor base, termos inicial/final, índice mencionado, juros mencionados, honorários, parcelas e, se mencionada, a emissão de RPV/Precatório com a respectiva data. |
| `validate` | Verifica coerência básica do payload extraído (datas plausíveis, valores numéricos), sem calcular. |
| `map_to_form` | Converte o payload no DTO do formulário (mesma estrutura aceita por `calculations`). |
| `finalize` | Persiste `SentenceInterpretation` com `status='extracted'` e retorna o payload ao front-end. |

### 10.2 Restrições

- O grafo **nunca** chama `CalculationEngine`.
- A saída do grafo é **apenas** o preenchimento do formulário.
- O usuário **revisa** e pode editar qualquer campo (RF12).
- O cálculo só ocorre por ação explícita do usuário (RF13), em endpoint distinto da app `calculations`.
- Campos não identificados na sentença ficam **vazios** para preenchimento manual; a LLM não inventa valores.

### 10.3 Contrato de Saída (DTO do formulário)

```python
# Conceptual shape returned by the graph (mapped to the form serializer):
# {
#   'base_value': Decimal | None,
#   'start_term': date | None,
#   'end_term': date | None,
#   'index_selection_mode': 'manual' | 'auto' | None,
#   'manual_index': str | None,
#   'interest_enabled': bool,
#   'attorney_fee_percent': Decimal | None,
#   'installment_mode': 'single' | 'multiple',
#   'rpv_issued': bool,
#   'rpv_issue_date': date | None,
#   'installments': [{'order': int, 'value': Decimal | None}],
# }
```

---

## 11. Interface

### 11.1 Princípios

- Todo texto exibido em **português brasileiro** (RNF02).
- Aderência rigorosa ao **design system** `@design_system/design-system.html` (RNF11): cores, componentes e tipografia exclusivamente desse arquivo.
- Layout responsivo dentro dos limites do design system.

### 11.2 Telas

| Tela | Conteúdo |
|------|----------|
| **Login / Cadastro** | Autenticação via Django auth. |
| **Painel** | Lista de cálculos do usuário (rascunhos e calculados). |
| **Importar sentença** | Área de texto para colar a sentença + botão "Interpretar". Exibe estado de processamento. |
| **Formulário de cálculo** | Campos de valor base, termos, modo de índice (manual/automático), juros de mora, honorários, parcelas (única/múltiplas, iguais/distintas) e checkbox "RPV/Precatório emitido" (que, ao ser marcado, revela o campo de data de emissão). Preenchido pela LLM quando vindo da importação; sempre editável. Botão "Calcular" (ação do usuário). |
| **Resultado** | Valor total atualizado + **memória de cálculo detalhada** (tabela de etapas: período, índice, fator, juros, subtotal). Opção de salvar/exportar. |

### 11.3 Fluxo de Revisão Obrigatória

O botão **"Calcular"** está presente apenas no formulário, após a interpretação. Não há rota que dispare cálculo automaticamente a partir da interpretação por LLM.

---

## 12. Plano de Desenvolvimento por Sprints

> Checklist detalhado de implementação. Cada tarefa descreve o que deve ser feito.

### Sprint 0 — Fundação do projeto

- [x] Inicializar o projeto Django com estrutura de apps (`core`, `accounts`, `indices`, `legislation`, `calculations`, `interpreter`).
- [x] Configurar `settings` com locale `pt-br`, timezone `America/Sao_Paulo` e banco SQLite padrão.
- [x] Configurar variáveis de ambiente para provedor de LLM (chave/modelo) sem hardcode.
- [x] Criar a base abstrata `TimeStampedModel` em `core` com `created_at` e `updated_at`.
- [x] Configurar runner de testes (Django nativo; `pytest-django` opcional) e pipeline mínimo de execução de testes.
- [x] Configurar linter/formatador alinhado à PEP 8 e à convenção de aspas simples.
- [x] Integrar o design system: incluir `@design_system/design-system.html` e mapear tokens (cores/tipografia/componentes) para os templates base.

### Sprint 1 — Autenticação e base de interface

- [x] Implementar `accounts` sobre `django.contrib.auth` (login, logout, cadastro) com Class Based Views.
- [x] Criar template base respeitando o design system (cabeçalho, layout, tipografia).
- [x] Implementar a tela de Painel (lista de cálculos do usuário) com CBV `ListView`.
- [x] Escrever testes de autenticação e de acesso restrito ao painel.

### Sprint 2 — Índices e cache local

- [x] Modelar `IndexType` e `IndexValue` em `indices` (herdando `TimeStampedModel`).
- [x] Implementar cliente da API do IBGE (INPC, IPCA-E) em `indices.services`.
- [x] Implementar cliente da API do BCB/SGS (SELIC, IGP-M, séries auxiliares).
- [x] Implementar a Tabela da Justiça Federal como índice carregável/parametrizável.
- [x] Implementar persistência de cache local em `IndexValue` com unicidade (index_type, reference_date).
- [x] Implementar fallback resiliente: usar cache quando a API estiver indisponível (RNF15).
- [x] Escrever testes unitários dos clientes (com mocks de HTTP) e do mecanismo de cache.

### Sprint 3 — Tabela de vigências (legislação parametrizável)

- [x] Modelar `CorrectionRule`, `InterestRule` e `UnificationRule` em `legislation`.
- [x] Criar data migration/fixtures carregando as regras das Seções 6.1, 6.2 e 6.3 como dados (nunca hardcoded no motor).
- [x] Implementar serviço `legislation.resolver` que retorna, para um intervalo, as regras de correção/juros/unificação aplicáveis.
- [x] Implementar tratamento do modo `ipca_plus_capped` (IPCA + 2% limitado à SELIC), conforme S6.
- [x] Escrever testes cobrindo transições de período (limites 1991/1992, 08-09/12/2021, 09/2025-10/2025).

### Sprint 4 — Motor de cálculo determinístico

- [x] Modelar `Calculation`, `Installment` e `CalculationStep` em `calculations`.
- [x] Implementar `CalculationEngine` em `calculations.services` usando exclusivamente `Decimal`.
- [x] Implementar validação de entrada (valor base, termos, percentuais, parcelas; rejeição de datas < 01/1984 conforme S3).
- [x] Implementar expansão de parcelas (única; múltiplas iguais; múltiplas distintas).
- [x] Implementar correção monetária por subintervalo (manual e automático).
- [x] Implementar juros de mora com regra de **não cumulação** a partir de 09/12/2021 (Seção 6.3).
- [x] Implementar a regra de **RPV/Precatório emitido** (Seção 6.4, S11): ponto de corte na data de emissão e substituição da correção por IPCA + 2% limitado à SELIC a partir dessa data; sem corte, manter SELIC.
- [x] Implementar cálculo de honorários sobre a base definida (S5).
- [x] Gerar e persistir a memória de cálculo (`CalculationStep`) para cada etapa.
- [x] Implementar arredondamento `ROUND_HALF_EVEN` e quantização final a 2 casas (S7).
- [x] Escrever testes determinísticos (mesma entrada → mesma saída) e casos de borda (transição de índices, parcelas distintas, não cumulação, RPV emitido com data dentro/fora do intervalo).

### Sprint 5 — Formulário de cálculo e resultado (interface)

- [x] Implementar formulário de cálculo (CBV) com todos os campos exigidos (RF01–RF08).
- [x] Implementar formset/estrutura para parcelas (única/múltiplas; iguais/distintas).
- [x] Implementar o checkbox "RPV/Precatório emitido" (RF18) que revela o campo de data de emissão quando marcado, com validação do intervalo (S11).
- [x] Implementar endpoint de cálculo disparado **apenas** por ação do usuário (RF13).
- [x] Implementar tela de Resultado com memória de cálculo detalhada (tabela de etapas).
- [x] Garantir que todos os textos da interface estejam em pt-BR e dentro do design system.
- [x] Escrever testes de integração do fluxo formulário → cálculo → resultado.

### Sprint 6 — Interpretação por LLM (LangGraph)

- [x] Modelar `SentenceInterpretation` em `interpreter`.
- [x] Configurar a camada LangChain (provedor de LLM via env var).
- [x] Implementar o grafo LangGraph com os nós `ingest`, `extract`, `validate`, `map_to_form`, `finalize`.
- [x] Implementar a tela "Importar sentença" (colar texto + botão "Interpretar").
- [x] Implementar o preenchimento do formulário a partir do payload extraído (RF11), deixando vazios os campos não identificados.
- [x] Garantir arquiteturalmente que `interpreter` **não importa** `CalculationEngine`.
- [x] Implementar a revisão humana obrigatória antes do botão "Calcular" (RF12, RF13).
- [x] Escrever testes do grafo (com LLM mockada) validando o contrato de saída (DTO do formulário) e a ausência de cálculo.

### Sprint 7 — Persistência, exportação e fechamento

- [x] Implementar salvar/recuperar cálculos do usuário (RF15).
- [x] Implementar exportação da memória de cálculo (CSV com BOM UTF-8 + estilos de impressão).
- [x] Implementar `signals.py` na app `calculations` para documentar contrato de limpeza em cascata.
- [x] Revisar mensagens de erro/validação em pt-BR (RF16) — correções em manage.py, services.py.
- [x] Cobertura de testes de ponta a ponta dos fluxos principais (5 novos testes E2E + exportação).
- [x] Revisão final de aderência: PEP 8, aspas simples, `Decimal`, design system, separação LLM × cálculo.

---

## 13. Critérios de Aceitação

| ID | Critério |
|----|----------|
| CA01 | Um cálculo com índice manual produz total e memória de cálculo coerentes e reproduzíveis. |
| CA02 | No modo automático, os índices/juros aplicados correspondem exatamente à tabela de vigências por período. |
| CA03 | A não cumulação a partir de 09/12/2021 é respeitada (sem dupla incidência de correção e juros). |
| CA03b | Com "RPV/Precatório emitido" marcado, a correção a partir da data de emissão é IPCA + 2% limitado à SELIC; sem marcação, segue pela SELIC. |
| CA04 | Múltiplas parcelas (iguais e distintas) são calculadas corretamente, com termos próprios. |
| CA05 | A memória de cálculo detalha período, índice, fator, juros e subtotal de cada etapa. |
| CA06 | A interpretação por LLM preenche o formulário sem disparar cálculo. |
| CA07 | O cálculo só ocorre por ação explícita do usuário após revisão. |
| CA08 | Índices são obtidos via API e servidos do cache local quando a API estiver indisponível. |
| CA09 | A tabela de vigências é editável em banco sem alterar o código do motor. |
| CA10 | Todas as models possuem `created_at` e `updated_at`. |
| CA11 | Todos os valores monetários usam `Decimal`. |
| CA12 | Toda a interface está em pt-BR e respeita o design system. |
| CA13 | Há testes automatizados cobrindo cálculo, legislação, índices e interpretação. |
| CA14 | O código está em inglês, segue PEP 8 e usa aspas simples. |

---

## 14. Riscos

| ID | Risco | Impacto | Mitigação |
|----|-------|---------|-----------|
| R01 | Indisponibilidade das APIs públicas (IBGE/BCB). | Cálculos no modo automático podem falhar. | Cache local persistente e fallback (RNF15); alerta ao usuário quando o índice não estiver disponível. |
| R02 | Interpretação incorreta da sentença pela LLM. | Dados errados no formulário. | Revisão humana obrigatória; LLM nunca calcula; campos não identificados ficam vazios. |
| R03 | Ambiguidade jurídica em transições de EC (113/2021, 136/2025). | Cálculo divergente. | Regras parametrizáveis em banco; suposições S6 e Seção 6.3 documentadas; testes de transição de período. |
| R04 | Uso indevido de `float` introduzindo erro de arredondamento. | Perda de precisão monetária. | Padrão obrigatório `Decimal` (RNF10) e revisão de código. |
| R05 | Acoplamento indevido entre `interpreter` e `calculations`. | Quebra da separação arquitetural. | Proibição de import cruzado; teste arquitetural verificando ausência do acoplamento. |
| R06 | Variação de formato dos dados retornados pelas APIs. | Falha de parsing/cache. | Camada de cliente isolada em `indices.services` com testes mockados. |
| R07 | Datas fora da cobertura legal (anteriores a 1984). | Resultado indefinido. | Rejeição explícita com mensagem clara (S3). |
| R08 | Desvio do design system. | Inconsistência visual. | Tokens centralizados; nenhum estilo fora de `design-system.html` (RNF11). |

---

## 15. Glossário

| Termo | Definição |
|-------|-----------|
| **Atualização/Correção monetária** | Recomposição do valor da moeda no tempo por aplicação de índice. |
| **Termo inicial / final** | Datas que delimitam o período de cálculo. |
| **Juros de mora** | Acréscimo pela demora no pagamento. |
| **Honorários advocatícios** | Verba devida ao advogado, percentual sobre a base definida. |
| **Parcela única / múltiplas** | Estrutura do valor a atualizar: um único montante ou diversos. |
| **Memória de cálculo** | Detalhamento auditável de todas as etapas e fatores aplicados. |
| **Índice** | Série econômica usada na correção (INPC, IPCA-E, IGP-M, SELIC, Tabela JF). |
| **INPC** | Índice Nacional de Preços ao Consumidor (IBGE). |
| **IPCA-E** | IPCA Especial (IBGE). |
| **IGP-M** | Índice Geral de Preços — Mercado. |
| **SELIC** | Taxa básica de juros; a partir de 09/12/2021 unifica correção e juros. |
| **Tabela da Justiça Federal** | Tabela de fatores de atualização do CJF/Manual de Cálculos. |
| **Tabela de vigências** | Conjunto de regras parametrizáveis por período (correção/juros/unificação). |
| **EC 113/2021** | Emenda que instituiu a SELIC como índice único a partir de 09/12/2021. |
| **EC 136/2025** | Emenda que instituiu IPCA + 2% a.a. limitado à SELIC a partir de 10/2025. |
| **LLM** | Modelo de linguagem usado para interpretar sentenças. |
| **LangGraph** | Framework de orquestração de grafos de agentes (sobre LangChain). |
| **DTO** | Estrutura de dados que representa o formulário trafegado entre camadas. |
| **CBV** | Class Based View (Django). |
| **Determinístico** | Mesma entrada produz sempre a mesma saída. |

---

*Fim do PRD — Juriscalc v1.0.*
