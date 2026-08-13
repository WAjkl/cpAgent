import type { Config, PartInfo } from '../types'

// 后端未就绪时的离线演示数据（基于 M2 config_gen 真实输出）
function part(p: Partial<PartInfo> & { model: string; price_cny: number }): PartInfo {
  return {
    price_source: 'estimate',
    confidence: 0.4,
    fetched_at: '2026-08-13',
    level: 'expired',
    ...p
  }
}

export const MOCK_CONFIGS: Config[] = [
  {
    id: 'cfg-mock-gaming',
    total_price: 7290,
    use_case: 'gaming',
    resolution: '2K',
    budget: 8000,
    score: { gaming: 74.2, productivity: 61.5 },
    parts: {
      cpu: part({ model: 'AMD Ryzen 7 7800X3D', brand: 'AMD', price_cny: 3000, price_source: 'live', level: 'fresh', socket: 'AM5', cores_threads: '8C/16T', confidence: 0.8 }),
      gpu: part({ model: 'RX 9060 XT', brand: 'AMD', price_cny: 3400, price_source: 'live', level: 'fresh', vram_gb: 16, vram_type: 'GDDR6', confidence: 0.9 }),
      motherboard: part({ model: '微星 B650M 迫击炮 WiFi', brand: 'MSI', price_cny: 899, socket: 'AM5', chipset: 'B650', form: 'M-ATX' }),
      memory: part({ model: '英睿达 16GB DDR5 5600 马甲', brand: 'Crucial', price_cny: 259, type: 'DDR5-5600', kit: '1×16GB' }),
      ssd: part({ model: '致态 TiPlus7100 1TB', brand: '致态', price_cny: 599, capacity_gb: 1024, interface: 'NVMe PCIe 4.0' }),
      psu: part({ model: '长城 X6 650W 金牌全模组', brand: '长城', price_cny: 399, wattage_w: 650 })
    },
    compatibility: { ok: true, problems: [] },
    price_freshness: { fresh: 2, stale: 0, expired: 4 },
    warnings: ['内存/SSD/电源/主板为估算价，装机前需实时刷新'],
    generated_at: '2026-08-13T20:00:00'
  },
  {
    id: 'cfg-mock-prod',
    total_price: 7832,
    use_case: 'productivity',
    resolution: '',
    budget: 8000,
    score: { gaming: 68.9, productivity: 84.0 },
    parts: {
      cpu: part({ model: 'AMD Ryzen 9 9950X', brand: 'AMD', price_cny: 3311, price_source: 'live', level: 'fresh', socket: 'AM5', cores_threads: '16C/32T', confidence: 0.8 }),
      gpu: part({ model: 'RTX 5060', brand: 'NVIDIA', price_cny: 2500, price_source: 'live', level: 'fresh', vram_gb: 8, vram_type: 'GDDR7', confidence: 0.9 }),
      motherboard: part({ model: '微星 B650M 迫击炮 WiFi', brand: 'MSI', price_cny: 899, socket: 'AM5', chipset: 'B650', form: 'M-ATX' }),
      memory: part({ model: '英睿达 16GB DDR5 5600 马甲', brand: 'Crucial', price_cny: 259, type: 'DDR5-5600', kit: '1×16GB' }),
      ssd: part({ model: '致态 TiPlus7100 1TB', brand: '致态', price_cny: 599, capacity_gb: 1024, interface: 'NVMe PCIe 4.0' }),
      psu: part({ model: '长城 X6 650W 金牌全模组', brand: '长城', price_cny: 399, wattage_w: 650 })
    },
    compatibility: { ok: true, problems: [] },
    price_freshness: { fresh: 2, stale: 0, expired: 4 },
    warnings: ['内存/SSD/电源/主板为估算价，装机前需实时刷新'],
    generated_at: '2026-08-13T20:00:00'
  }
]

export const MOCK_REPLY =
  '以下是为你的预算和用途生成的配置单（数据来自硬件库 v2.1，价格来源与快照时间已标注）。\n\n注意：**内存/SSD/电源/主板为估算价**，装机前建议实时刷新。'
