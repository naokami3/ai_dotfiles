---
name: secret-management-policy
description: シークレット管理を最小化し、モダンな代替手段（IAM認証、Workload Identityなど）の採用を検討する。
---

# シークレット管理のモダン化

このスキルは、シークレットを持つこと自体の必要性を問い、持たなくて済むモダンなアプローチを提案します。

## シークレット削減の検討事項

1. クラウドクレデンシャルキー: GitHub Secretsに生で置かず、AWS STS AssumeRoleやGoogle Cloud Workload Identityによる権限借用への移行を検討する。
2. APIキー: パブリックAPIはOAuth/OIDC、プライベートAPIはIAM認証への移行を検討する。WAFやApp Checkなどの多層防御は必須とする。
3. DBアカウント/パスワード: マネージドDB（RDS/Cloud SQLなど）であれば、IAM認証を利用してDB固有のパスワード管理を削減することを検討する。

## シークレットの参照方針

- 実行環境: 基本的にSecret Managerを使用し、都度参照によるコスト増を避けるためインメモリキャッシュを実装する。
- CI/CD: GitHub Secretsはクラウドへの権限借用やCI/CD固有の値など、必要最小限に絞る。
