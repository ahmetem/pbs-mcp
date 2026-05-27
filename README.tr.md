# pbs-mcp

**Proxmox Backup Server** için MCP server. PBS REST API üzerinden datastore
durumu, snapshot envanteri, garbage collection, verify ve prune işlemlerini
13 LLM-callable tool olarak sunar.
[Model Context Protocol](https://modelcontextprotocol.io) için tasarlandı.

For English → [README.md](README.md)

## Neden

PBS'in zaten güzel bir web arayüzü var. Bu server, "şu an UI'da değilim ama
PBS hakkında soru sormam lazım" durumları için. Bir sohbet asistanından
"bir şey bozulmuş mu?" diye sorabilmek; veya bir homelab agent'in gerçek
duruma göre verify ve prune planlayabilmesi için.

## Tool'lar (13)

| # | Tool | Mod | Not |
|---|------|-----|-----|
| 1 | `pbs_list_datastores` | read | Yapılandırılmış datastore'lar + scheduler |
| 2 | `pbs_datastore_status` | read | toplam / kullanılan / boş byte |
| 3 | `pbs_list_groups` | read | Snapshot sayısı, owner, corrupt flag |
| 4 | `pbs_list_snapshots` | read | Boyut, dosya, son verify state, protected flag |
| 5 | `pbs_get_task_status` | read | UPID → running / OK / error |
| 6 | `pbs_get_task_log` | read | Task log'unu tail veya sayfala |
| 7 | `pbs_list_tasks` | read | Son task'ler, isteğe bağlı filtre |
| 8 | `pbs_gc_status` | read | Son GC istatistikleri: referans, pending, kaldırılan |
| 9 | `pbs_run_gc` | **write** | GC tetikle, UPID döner (async) |
| 10 | `pbs_run_verify` | **write** | Verify tetikle, isteğe bağlı snapshot scope |
| 11 | `pbs_prune_dry_run` | read | Hangi snapshot'lar silinecek önizleme |
| 12 | `pbs_prune` | **write** | Retention policy uygula |
| 13 | `pbs_forget_snapshot` | **write** | Tek snapshot sil (corrupt cleanup) |

Write tool'ları **iki şartı** birden ister: ortamda `PBS_ALLOW_WRITE=true`
ve çağrıda `confirm=true`. Restore burada yok — standart `proxmox-mcp`
zaten Proxmox VE tarafından PBS'ten restore yapabiliyor (`archive=...`).

## Kurulum

### 1. PBS'te API token oluştur

PBS host'unda shell aç (PBS bir LXC'de ise Proxmox'tan `pct enter 205`,
değilse direkt SSH):

```bash
# root@pam altında token üret
proxmox-backup-manager user generate-token root@pam mcp

# Datastore'da admin yetkisi ver
proxmox-backup-manager acl update /datastore/<datastore-adın> \
  DatastoreAdmin --auth-id 'root@pam!mcp'
```

`generate-token` çıktısındaki `value` alanı **secret** — sadece bir kez
gösterilir, kaydet.

> Neden DatastoreAdmin? PBS prune'da owner check yapıyor. Ya token'a
> DatastoreAdmin verirsin (bu yöntem), ya da her backup push'tan sonra
> `change-owner` ile sahipliği transfer edersin. Admin scope daha basit
> ve tek bir datastore'la sınırlı kalıyor.

### 2. MCP server'ı yapılandır

```bash
git clone https://github.com/ahmetem/pbs-mcp.git
cd pbs-mcp
cp .env.example .env
# .env'i düzenle: PBS_HOST, PBS_TOKEN_ID, PBS_TOKEN_SECRET
pip install -e .
```

### 3. MCP client'ına kaydet

Claude Desktop için `claude_desktop_config.json` dosyasına ekle:

```json
{
  "mcpServers": {
    "pbs": {
      "command": "python",
      "args": ["/mutlak/yol/pbs-mcp/pbs_mcp.py"]
    }
  }
}
```

Client'i yeniden başlat. `pbs_*` tool'ları görünmeli.

## Güvenlik modeli

* **Varsayılan read-only.** Kurulumdan sonra `PBS_ALLOW_WRITE=false`, bu
  yüzden write tool'lar `confirm` ne olursa olsun reddediyor.
* **İki anahtar şartı.** `PBS_ALLOW_WRITE=true` kapıyı açar; her çağrı
  ayrıca `confirm=true` ister. İki bağımsız bilinçli aksiyon.
* **Async task'lar sonuç değil UPID döner.** `run_gc` ve `run_verify` işi
  başlatıp hemen UPID veriyor. `get_task_status` ile takip ediyorsun.
  MCP isteği saatlerce bloklanmıyor.
* **Token tek datastore'a bağlı.** ACL'ler `/datastore/<isim>` üzerinde,
  `/` üzerinde değil. Sızıntı durumunda token PBS kullanıcı listesini
  veya remote sync config'ini okuyamaz.

## Notlar / gotcha'lar

* **İlk çağrıda cache gecikmesi**: PBS ACL'leri birkaç saniye cache'ler.
  Yetki verir vermez "permission check failed" alırsan 3 saniye bekle ve
  tekrar dene.
* **Token izinleri vs user izinleri**: PBS API token'ları, parent user'ın
  ACL'leri ile kendi ACL'lerinin kesişimini alır. `root@pam!mcp` ile parent
  superuser, pratikte sadece token'ın ACL'i geçerli.
* **Self-signed sertifika**: PBS varsayılan olarak self-signed sertifika ile
  gelir. LAN kurulumu için `PBS_VERIFY_TLS=false` yeterli. Gerçek CA için
  `PBS_VERIFY_TLS=true` ve `PBS_CA_BUNDLE` ile PEM dosyası yolu.
* **UPID'ler yaratıcılarına bağlı**: silinen bir kullanıcının başlattığı
  UPID artık okunamaz hale gelir. Pending task varken PBS user'larını
  silme.

## Lisans

GPL-3.0-or-later. [LICENSE](LICENSE) dosyasına bak.
