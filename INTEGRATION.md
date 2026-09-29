# Integrate with DocAI workflows

The canonical [integration guide](backend/docai/docs/integration.md) is packaged with Django and served at
`/api/docs/integration.md`, under the same access policy as the API reference. Start with `/api/llms.txt`
for the concise agent journey or `/api/docs/` for Swagger.

For a terminal or automation client, install and use the standalone HTTP-only [`docai` CLI](CLI.md). It shares this
API contract and does not import Django.

For optional Scalar installation and deployment routing, see [API documentation](docs/api-documentation.md).
