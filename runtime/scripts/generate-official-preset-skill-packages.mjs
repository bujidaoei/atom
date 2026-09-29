import { Buffer } from 'node:buffer';
import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

import { unzipSync } from 'fflate';
import { fetch } from 'undici';

const catalogPath = 'packages/data-access/src/v3/official-employee-templates.json';
const outputPath = 'packages/data-access/src/v3/official-preset-skill-packages.ts';

const ROLES = [
  {
    roleType: 'common-frontend-developer',
    roleTemplateVersionId: '33000000-0000-4000-8000-000000000013',
    sourceDirectory: process.argv[2],
    expected: {
      'accessibility-audit': {
        packageSha256: '47dd9a4e69dfb942fbd433ed088f5e044f98bd0f401a5e5e0029137417106830',
        contentSha256: 'cbc2514868de9ee19a4f736b2e6294bc386fa052080443276cead790632a5ac5',
        inventorySha256: '050264864308cccffec5ce398de1e6a5d0ee8f41eec8df604334ccb285198de4',
        treeSha256: '033802c761bdb2a8e8666a78481f36512b840898510d13727586832186578b04',
      },
      'browser-harness': {
        packageSha256: 'eef05a77cfa8bc8561bc115ca06ec032e3dae8917191575d191069fb4b5d387c',
        contentSha256: '413ccce82de1b0fe06d95ad64565dc2ed9b4ca16f45ef83d88d939eca8cec211',
        inventorySha256: 'f3a737e2e3950315c395ea35dc0efdcd0fd33add98d83242b256557bfb80ba4b',
        treeSha256: '27dd1a7ab0e297978ebd95bd189f8212136bdcfc97bc62c369fc49c96ded52f7',
      },
      'change-validation-planner': {
        packageSha256: 'c26cccf6a568a0bf1105a5706df2095da614448c6085e966a21c832b68dd8d24',
        contentSha256: 'a18c76cf4bde5f331135b21efdc2c4aa76fe4f06d200285bfa9110c3363c9727',
        inventorySha256: '050264864308cccffec5ce398de1e6a5d0ee8f41eec8df604334ccb285198de4',
        treeSha256: 'b12997569d2141e49aaa239a46509835e0c935f3d2518099e9fee1e0cb3bf331',
      },
      'component-architecture': {
        packageSha256: '40d885ae46e0b2d9ed0e90548e82e40f909243b24dbab4a1dd2d1deb4890d708',
        contentSha256: '0f4df303ae4b4fd2987a0a23afc88f08093b9eb23a72692abc6c2c8776967253',
        inventorySha256: '050264864308cccffec5ce398de1e6a5d0ee8f41eec8df604334ccb285198de4',
        treeSha256: '707d0561a66e2651d4a2330f691159f0402d8213c4e7f61b73d704ae17bacb6d',
      },
      'design-system': {
        packageSha256: '80bbd66046b8c6b8a12ac0ad8e7da62ec7fa1802f5226ad465abd70e5b140188',
        contentSha256: '886bc663e8699b68df805517cb69928ac3f384c45afbdc2b06c2605b69a926a0',
        inventorySha256: '050264864308cccffec5ce398de1e6a5d0ee8f41eec8df604334ccb285198de4',
        treeSha256: 'a9eb403f306de38a2109b2c809327e45822438712cf36ae6bab3a8594f12d7a7',
      },
      'front-design': {
        packageSha256: '74a5fe44284c9f5058be4ed7bb909586004f24c57f980d7740c8ddc80c31d63b',
        contentSha256: '33d9198678be2f040ea0fd7fa1fed2c43860408351c0a98b50c3aa55f842a4f5',
        inventorySha256: '050264864308cccffec5ce398de1e6a5d0ee8f41eec8df604334ccb285198de4',
        treeSha256: '1d82db71eca6b81f5e6a68c0bef9595b204b111117d7ece4c0d08fe7c05960d8',
      },
      'performance-optimization': {
        packageSha256: 'f74f437dd9fbc23e3ccf13524dc0a9fe2768c25fb0ea7c90799501b5c5b0a38d',
        contentSha256: '68b1776f5e73bb3ab0211cba3b9313e75fe9bdce85b708c1cbbe3ceb69b55ecb',
        inventorySha256: '050264864308cccffec5ce398de1e6a5d0ee8f41eec8df604334ccb285198de4',
        treeSha256: 'ece5da49ee6d45af273e5e0fa216a9092042b2ac3f83c4291c7ef6e28be54709',
      },
      'responsive-design': {
        packageSha256: 'e7794567b3760cfe3e35e918a947db10d00b35f615a40a493ff4e3159eb28c7f',
        contentSha256: 'dd5553762e186f607f3437b11cbf67b923c56b332e759fa0cd9846916ac36c64',
        inventorySha256: '050264864308cccffec5ce398de1e6a5d0ee8f41eec8df604334ccb285198de4',
        treeSha256: '705b3901ea152f6c0a513c356fc435fc6db17ca1800e8541d3f3ad1128349d97',
      },
    },
  },
  {
    roleType: 'common-product-manager',
    roleTemplateVersionId: '33000000-0000-4000-8000-000000000012',
    sourceDirectory: process.argv[3],
    expected: {
      'browser-harness': {
        packageSha256: '38b7e24d81df35541d04428bdebc9bfc8a0c8ab98e3628ea4dcffdbc6c2dd8cf',
        contentSha256: '413ccce82de1b0fe06d95ad64565dc2ed9b4ca16f45ef83d88d939eca8cec211',
        inventorySha256: 'f3a737e2e3950315c395ea35dc0efdcd0fd33add98d83242b256557bfb80ba4b',
        treeSha256: '99e69d3ce69df766a2393ff7d10e0cfc0e35769a047ff743ebf11bc9ea80fe22',
      },
      'changelog-management': {
        packageSha256: '19852585bbda4cda5c08464acc910e2457e522574bbf9554bd4851728767285b',
        contentSha256: '276f8a21e5315d7378d0b6cb7beb233fafa82700ea7813c7d51ec2940998ee9e',
        inventorySha256: '050264864308cccffec5ce398de1e6a5d0ee8f41eec8df604334ccb285198de4',
        treeSha256: 'aabcb893948bd6fd800a20ec97e3051ade1d8dba3839122896631266118be87a',
      },
      'competitor-research': {
        packageSha256: '3204a386fbf3fc82a6e62fe6d851bc6cd1029a1b077ff44d7b4f2b13a15c13ae',
        contentSha256: '060c46ff539da8564a96a70c42049c39fd80b7a77f0f6fa1f76e28f78a74eead',
        inventorySha256: '050264864308cccffec5ce398de1e6a5d0ee8f41eec8df604334ccb285198de4',
        treeSha256: '6368a2a4507815b286c23ffcb1ffc7929e43ecfa890044209767900df07e9675',
      },
      'prd-generation': {
        packageSha256: '4849a8c0886d7c553c4d03cafad635582368ea1138b9e14b54639610e0836b79',
        contentSha256: '0047c39d6be9b3a084e6620bb749b6e1b087103ca123c8f60d300282d71fea14',
        inventorySha256: '050264864308cccffec5ce398de1e6a5d0ee8f41eec8df604334ccb285198de4',
        treeSha256: '278633a0e1ffa28177839750f25ee518ae8368a82265ccf449c2c69cb32e2157',
      },
      'requirement-pool-management': {
        packageSha256: '57b1b09b392a372a3046f76ec22a7a19aed6496f37f89359dabed5ce9790c5d7',
        contentSha256: 'c27f65d0e10214e1e1a9bf8dce48320d22c1b081d12f7e5ce17b9da9f2b41e0c',
        inventorySha256: '050264864308cccffec5ce398de1e6a5d0ee8f41eec8df604334ccb285198de4',
        treeSha256: '24c099707812fffb913474605859546c96276c0b35138c927a829c5b48b25e29',
      },
      'user-feedback-analysis': {
        packageSha256: '7d77b26640f91cf42437b9c344e90881c4e85097d4a632b5e652ecbfd7993e2d',
        contentSha256: '89d1cabd8e36aaf2d7a1380c734c75674c1dfbd0ac2296f0aa5aa5e4ce9929cd',
        inventorySha256: '050264864308cccffec5ce398de1e6a5d0ee8f41eec8df604334ccb285198de4',
        treeSha256: 'c4a2c7136b6861ea411265587ced9bb40db4187299f70d1da6a9a773e7ebc1a0',
      },
    },
  },
  {
    roleType: 'project-administrator',
    roleTemplateVersionId: '33000000-0000-4000-8000-000000000014',
    sourceDirectory: process.argv[4],
    expected: {
      'cross-functional-coordination': {
        packageSha256: 'a1e016970bc794d8a8f52c944ed856647a25bfcf6a051d624aa16cdc30460920',
        contentSha256: '80973c6083cbd59c690b56c3fd0538a6dd39859d22b1d96c01c126cd7c004e04',
        inventorySha256: '050264864308cccffec5ce398de1e6a5d0ee8f41eec8df604334ccb285198de4',
        treeSha256: '5fc499820ee77cfb1a996405d6460dcfdf57611038541fab82b4f9f5e26ea7c2',
      },
      'meeting-decision-management': {
        packageSha256: 'b9007a68b203c4312adbb20cc78ac535dd48931d497680ebdaed70755deaae62',
        contentSha256: 'bb8cdb88091497d649d11131c1c460e9819400092cbaf03ed71c8e6061151ba6',
        inventorySha256: '050264864308cccffec5ce398de1e6a5d0ee8f41eec8df604334ccb285198de4',
        treeSha256: 'c2051e88edc5a9aac697935d592a2fcc44a64557f31b330ad2ce38ed554e344c',
      },
      'project-planning': {
        packageSha256: 'b3f7d6359e86f37ea45bcd95d3fa0518c85df77678e3c18008ddbadc8a898302',
        contentSha256: '48ed9b2b776d1158e9b3164c96a39d8bef0ca597d351cf6957831285885d28cf',
        inventorySha256: '050264864308cccffec5ce398de1e6a5d0ee8f41eec8df604334ccb285198de4',
        treeSha256: 'acb0397de61565c0b279474d6d7a4a23512b6174f63df91f478847613c9e332d',
      },
      'release-handoff-management': {
        packageSha256: '35b530779f1bb5ececb611be62ba27e9280e11f163c84249d21524e3f017413c',
        contentSha256: '136b0eb9ee44ce85d65eb2b962004dd45f9adb2c7eefcafa1a663d34b1711321',
        inventorySha256: '050264864308cccffec5ce398de1e6a5d0ee8f41eec8df604334ccb285198de4',
        treeSha256: '4d5fd9683094ef2c96a24a3a508c19635ed0396c93a3fd75307123b3127ae268',
      },
      'status-risk-reporting': {
        packageSha256: '01dbe7f9779f10a2eb68733093044221190b36dc204eabdf506032b31004dc27',
        contentSha256: 'a4e372120d3dfbe03266bd9d8b647f5f02c689dfb6bf5cfa8a98a829db413409',
        inventorySha256: '050264864308cccffec5ce398de1e6a5d0ee8f41eec8df604334ccb285198de4',
        treeSha256: '23b082d12b1bf94fba2173564603ac88bb2047eb933decbc74e7ed362e8341ce',
      },
      'task-breakdown': {
        packageSha256: 'b04d5e7b83d4919bc569c27c6141f15f37de753462f19987b836dddd73ee921b',
        contentSha256: '3638b4d25f82d6d49d0e226159b8eb0d0f0837419887fb4ee0f0ecbb8ba9f1a3',
        inventorySha256: '050264864308cccffec5ce398de1e6a5d0ee8f41eec8df604334ccb285198de4',
        treeSha256: '2a97c847ec0fa7251eb68085afbc7c43fdf3f09ed3304cb66b0b0b0802a1dbb4',
      },
    },
  },
  {
    roleType: 'ux-ui-designer',
    roleTemplateVersionId: '33000000-0000-4000-8000-000000000015',
    sourceDirectory: process.argv[5],
    expected: {
      'figma-design-handoff': {
        packageSha256: '63615b57ead33f64fe9bc390646efbf96906f5c754ec804ff0a3bbb0fa48df68',
        contentSha256: '16a96b9c40233a8992ed53bfc6878cd9d9de0b31b8ca274e5ec39beb0fbb6fb9',
        inventorySha256: '050264864308cccffec5ce398de1e6a5d0ee8f41eec8df604334ccb285198de4',
        treeSha256: '92206feda04bcb59ad7704024637544010ea7cef63418dd4fc89c43d23ec0a0a',
      },
      'spark-design': {
        packageSha256: '5046ee3d4994a13a9028de65d8ad845ea6a461d35229796f952f0c82360088eb',
        contentSha256: '201060d13b299a5fadef7f1061488c093c79a8c91d510d0200f3062df06d6c5f',
        inventorySha256: '454581da3071c691f9bc16700ae6fd1126d71ca8403c3e899e5ecb8cb0da58b0',
        treeSha256: '710ef6aec170a07c7b62b6756d92d37ccff5fbd01eb3bcf92ddbe24862ac16fc',
      },
    },
  },
  {
    roleType: 'common-qa-engineer',
    roleTemplateVersionId: '33000000-0000-4000-8000-000000000016',
    sourceDirectory: process.argv[6],
    expected: {
      'accessibility-audit': {
        packageSha256: 'abc0391c35141d05a408991e8f07162200b17cdf72773693b14c38a594209f8a',
        contentSha256: '9705c0f62b9e5c5eb6a2b96f46772b77bb351a0d12e41f6d2c4ba22f9c4b4556',
        inventorySha256: '050264864308cccffec5ce398de1e6a5d0ee8f41eec8df604334ccb285198de4',
        treeSha256: '142ec2e01640adc9adea0eeead60f18a34ddcd094f6abafb5d9fecf92b9cc6c8',
      },
      'browser-harness': {
        packageSha256: '80d01a4563401636a28db1947ebfe48f3504739fe7a0b416efe2c0caec73c400',
        contentSha256: 'b591c2b3166acce678781cef49fa5bdde103fea361536000068c464ed2186dc7',
        inventorySha256: '050264864308cccffec5ce398de1e6a5d0ee8f41eec8df604334ccb285198de4',
        treeSha256: '5ec07ce460d1043fca6ff75aec36031d0e6c4d6faca8fcd751c1780401077b57',
      },
      'change-validation-planner': {
        packageSha256: '6321601124e575e2ee1b688f0357e92ed50322b867c323061ed0fc69ccd6c768',
        contentSha256: '2cb64d7feeaa8d3d4fbc9518b2cd3136b55e45acb297b05a832dd7ee2264615e',
        inventorySha256: '050264864308cccffec5ce398de1e6a5d0ee8f41eec8df604334ccb285198de4',
        treeSha256: '8c6835eb22ecc3d331bb45f35da12a20b5fdf4b2c2aa5ddbfffcd22e9b915032',
      },
      'github-developer-communication': {
        packageSha256: 'f4971aaa50342b5ef90a3d2782047a211eefaa006ef5cff702da82feca020aa1',
        contentSha256: 'a64a449f6b028cd043bff6ad5b2691f2b22d807dc95f21d295cd30458546836b',
        inventorySha256: '050264864308cccffec5ce398de1e6a5d0ee8f41eec8df604334ccb285198de4',
        treeSha256: 'c1e0bd2bcaaf597a1914d0d37ac73dc8c9908e9c423062d7c87bba3821f60ddd',
      },
      'responsive-design': {
        packageSha256: '90dde56cfc8e99d5fb71cd93dd071539a5593e70f0ef7615a3b0b5b258292424',
        contentSha256: 'e06bbcb03a26b42227c5dfa347d4ebe21c192e5d529e5883222534fff3e115dd',
        inventorySha256: '050264864308cccffec5ce398de1e6a5d0ee8f41eec8df604334ccb285198de4',
        treeSha256: 'bb36aa10a74aa9e4643fcfe94f122b1713c8dd58e5726fc03f2e7f788bd888e1',
      },
      'test-case-template': {
        packageSha256: '1c9b911b1bb9c2f4786e98b66d7ee513f84b1dd0b3fcaba83f805d9ddbd65688',
        contentSha256: 'd81da485697de2f23ec5a54abf64bd72302d35d1d87c92c38d049968a5931abf',
        inventorySha256: '050264864308cccffec5ce398de1e6a5d0ee8f41eec8df604334ccb285198de4',
        treeSha256: '1bc7635f4e43cc6dbad991681dc581227cce205d741f55f066c4a9eaaf7ff0ec',
      },
    },
  },
  {
    roleType: 'devops-engineer',
    roleTemplateVersionId: '33000000-0000-4000-8000-000000000017',
    sourceDirectory: process.argv[7],
    expected: {
      'ci-cd-pipeline': {
        packageSha256: '65245c3676fb1e61eefb003fbe437722ffa60c913f13197efcccea3263be78aa',
        contentSha256: '6aacda37e902c48c6397ce3dfb843c64b524bf14aa2fbabb968fb70ef7f343ae',
        inventorySha256: '050264864308cccffec5ce398de1e6a5d0ee8f41eec8df604334ccb285198de4',
        treeSha256: '7c7e2cfa8edf390201239f51c9c91f41f62d23ca652b1af21ef576e5be6cf894',
      },
      'environment-management': {
        packageSha256: '363144b5d8da8e52ea53c38aceb98a16be46c1f98a65891a836b3c078a56f361',
        contentSha256: '5ceb3a70416f260c2cd2e91087a7f9f2488d6558611527134835ec31e98f8b21',
        inventorySha256: '050264864308cccffec5ce398de1e6a5d0ee8f41eec8df604334ccb285198de4',
        treeSha256: '73ff2794e28f81ca4ff00439b6bf061da99822ac961e3830db9155afbee75896',
      },
      'infrastructure-automation': {
        packageSha256: 'b36ab17a32c5abf6771153cc095cf660eca49e49e01d579125fd327da55b3810',
        contentSha256: 'd853f7071fb00501fb4a264f897ac1d76750fefc71bde311e7c4be0ff2d5355d',
        inventorySha256: '050264864308cccffec5ce398de1e6a5d0ee8f41eec8df604334ccb285198de4',
        treeSha256: 'ee8fb6eb153085d456d07f679c061172dc6a6775329fca597cb83a85fd037b14',
      },
      'observability-integration': {
        packageSha256: '79964a0d5098640dbd2f286a2fe28caef2eece6edf2535a118739ca2220603ed',
        contentSha256: 'd57e350dd2544b2e567a3e397e04aef972639c9ad30917c9513af5c3435f50bb',
        inventorySha256: '050264864308cccffec5ce398de1e6a5d0ee8f41eec8df604334ccb285198de4',
        treeSha256: '75c70d253d9bd45221410952967ccf592ab2cd05c6043eb2623d18f4dfc53aa9',
      },
      'release-rollback': {
        packageSha256: '15d339d7a3862dbc67ab86b4993f11b561be72cea25675fd8d782d862286ca0c',
        contentSha256: 'beca1614ddf9e23ffd09bf75defce496ed51f6b6395d2ef5ac2c0efbb7aba151',
        inventorySha256: '050264864308cccffec5ce398de1e6a5d0ee8f41eec8df604334ccb285198de4',
        treeSha256: 'b8f7e6e063742a45806e9a9bbd28d5fca8cd820024c3a26b81df13c080c5a787',
      },
      'secret-config-governance': {
        packageSha256: 'cdb029609b5743b5da1e6287466111265788ee18adf886474733570870242fa9',
        contentSha256: '8dfa571c7011e19ef2f031c222f8385a530207c7d4ccc09773b65b760546edca',
        inventorySha256: '050264864308cccffec5ce398de1e6a5d0ee8f41eec8df604334ccb285198de4',
        treeSha256: '3fbc68a3bce2bdf39c37e320f79d81d28675777cda38749264468d69f6c4df6c',
      },
      'security-scan-gates': {
        packageSha256: 'f2e1973f5501f5de9ee528e45ea362c451fbd2cc22bdd8556f81ef80b253af92',
        contentSha256: '31d5600c5d4f2f5671052efd27ddb2bd5d712dbb143f0a0e1c39e21a946dc582',
        inventorySha256: '050264864308cccffec5ce398de1e6a5d0ee8f41eec8df604334ccb285198de4',
        treeSha256: 'a55821ce83d971a6d9c2433a42c33a80e5de253ac4d3eeff36bd3ff9c5b69fa5',
      },
    },
  },
  {
    roleType: 'operations-engineer',
    roleTemplateVersionId: '33000000-0000-4000-8000-000000000021',
    sourceDirectory: process.argv[8],
    expected: {
      'alert-triage': {
        packageSha256: '78ce54e5654d927d533044b8e59c38fdca184934424b7a152c8faa02182f7230',
        contentSha256: '70717c71e7da6ec5aec0cecf1f24cdd699d69517f3744726b7ea5e78f97be711',
        inventorySha256: '050264864308cccffec5ce398de1e6a5d0ee8f41eec8df604334ccb285198de4',
        treeSha256: '35ad7acdfdfa65033c4b46f0dc815791efb3e383c0c49787b5d26446f47faa06',
      },
      'backup-recovery-check': {
        packageSha256: '6434cfd28e023bd17038775e8ff329551181b0256d4776fff01ccab18ba936ab',
        contentSha256: 'db76ea063fc79f4e905f8fe1243a1ece6b192794fda8552ba5c9ddac8ae71efa',
        inventorySha256: '050264864308cccffec5ce398de1e6a5d0ee8f41eec8df604334ccb285198de4',
        treeSha256: 'd92221f69b31405fea2632e71eb6fccf36bb5a9dbc14612e566a31d049b91f5e',
      },
      'capacity-health-review': {
        packageSha256: '96fb336450ba3c6c6aeed2155dc93880a6eec1d8fa2fe45968e4c89f12859ceb',
        contentSha256: 'c48584464209b376bbb77e14600cc8d8616bece676a9f3a19fd71aa3c38fbb05',
        inventorySha256: '050264864308cccffec5ce398de1e6a5d0ee8f41eec8df604334ccb285198de4',
        treeSha256: 'a8051670a1d41f1081c22382e308a33334f967612e8b47f9e490e8dcf23dbca3',
      },
      'daily-ops-check': {
        packageSha256: '2606b71f68f3f515d372a4f1fccb515ea3f82a63f079bf2a90227e7b2a1a67ed',
        contentSha256: 'cfc1e72ffa20fe78f8ecdbf040ffbb8e2d7fccab9f465e8abff96c3862bd5f00',
        inventorySha256: '050264864308cccffec5ce398de1e6a5d0ee8f41eec8df604334ccb285198de4',
        treeSha256: 'f046bce6a3b452a3fef9ad62b70926899131aa4a3a9c70ec748b3b9f634509f7',
      },
      'incident-triage': {
        packageSha256: 'afd2a44b702ff92906e73cb5cc5d7a4228c76210e366088103d7b206f47175be',
        contentSha256: 'c6b63f965888c18d6ce4678e318232a1ea87a48a2b0ecb2fce58040059215625',
        inventorySha256: '050264864308cccffec5ce398de1e6a5d0ee8f41eec8df604334ccb285198de4',
        treeSha256: '0ea56aeff8e6733cbe08bc95abd06f6d4f217673952d29f1c2909db638a47cd3',
      },
      'ops-reporting': {
        packageSha256: 'c07b0e8674363367aec451f2309d7426b1516f2e403b596acf668d270645eb07',
        contentSha256: '07db140fe0a108f860094ceead5c7a5df3e65847cd5b359262c0b526a23a4b30',
        inventorySha256: '050264864308cccffec5ce398de1e6a5d0ee8f41eec8df604334ccb285198de4',
        treeSha256: '13eae07433fb82baf9f9527b2eef6a803c6de0f708819e92ddd1eae9fb749f39',
      },
      'runbook-maintenance': {
        packageSha256: '0b03c83c2d80a36fd71445f94aead5c9e3d2a167e3933c1336a021683921a0da',
        contentSha256: '97fa64bf9d26091611493cd9c1686cbfd4afe4dba04ee885927cc07629545c9d',
        inventorySha256: '050264864308cccffec5ce398de1e6a5d0ee8f41eec8df604334ccb285198de4',
        treeSha256: '191b56c2653ef1b1c3ff999ad232484de97330049d0ba581b592eaf89d2d3d93',
      },
    },
  },
  {
    roleType: 'common-data-analyst',
    roleTemplateVersionId: '33000000-0000-4000-8000-000000000018',
    sourceDirectory: process.argv[9],
    expected: {
      'analyst-competitor-research': {
        packageSha256: '09626777a1a0bb84591d220fb28cb3a7f6d6ab5812934d389c40079a59ac4a15',
        contentSha256: 'f49f744eadc38b0c44506755252b9bb6c49f71714253ab4b49e368fd7a6d7678',
        inventorySha256: '050264864308cccffec5ce398de1e6a5d0ee8f41eec8df604334ccb285198de4',
        treeSha256: '19e24542ec7e1ca88223251b612f7c5740eb39146ed859bb68ccf6b6e38d0ee3',
      },
      'analyst-insight-reporting': {
        packageSha256: '8940d14abd38751edfdbe90f17b56271eabdb93adcf926492f247caae59cc8e7',
        contentSha256: '36760c864a02526d43c08f4dda58a21298c3a92c1797e589d7c630074ecfdd65',
        inventorySha256: '050264864308cccffec5ce398de1e6a5d0ee8f41eec8df604334ccb285198de4',
        treeSha256: 'adb5e76f4658b75f791e73687db16fea8898678475ebafaade392d1a76d38650',
      },
      'analyst-metric-dictionary': {
        packageSha256: '62052c66bb0327c4bab81b1ab55f55550ea0055701329e419bda0869eb6411e4',
        contentSha256: 'e05d31d1685fb14ebd82f9ced1bd49244c71077d879a924cae7308a3d5ee6d23',
        inventorySha256: '050264864308cccffec5ce398de1e6a5d0ee8f41eec8df604334ccb285198de4',
        treeSha256: '59af800fcb516ecbfdc6944fd239f34dc4837d1261b998bcb3be1d6dd1aed1eb',
      },
      'analyst-problem-framing': {
        packageSha256: '7d29cc47916c93526fe796cdafd18788980f144ca85068c787f868b83f5e2dc0',
        contentSha256: 'b1ce110ce4354f04203ef15227dd9c621d805897018cbb3b366f48d98571a894',
        inventorySha256: '050264864308cccffec5ce398de1e6a5d0ee8f41eec8df604334ccb285198de4',
        treeSha256: '653655c6491f0ed1962a84afa5ca8f3787347ba9ff745ee93c8053b45ef3271e',
      },
      'analyst-traffic-analysis': {
        packageSha256: '5a19611eba72c5bd5437dc4d04fe02cd972ad0f0491110b573fb45344ace2886',
        contentSha256: '64729df8c0cbeb12423683053827d94a2dde807b572077d2bb99966bedbc57a4',
        inventorySha256: '050264864308cccffec5ce398de1e6a5d0ee8f41eec8df604334ccb285198de4',
        treeSha256: '46fc0455dc0d1c634571655957a666a419a754da4935bdf785bde8969bfacd8e',
      },
      'browser-harness': {
        packageSha256: '5704d427e68cb8b46666f421c0ae6e09f9c5cec20a3ebdb02e1dfabf8a37288f',
        contentSha256: '413ccce82de1b0fe06d95ad64565dc2ed9b4ca16f45ef83d88d939eca8cec211',
        inventorySha256: 'f3a737e2e3950315c395ea35dc0efdcd0fd33add98d83242b256557bfb80ba4b',
        treeSha256: '27dd1a7ab0e297978ebd95bd189f8212136bdcfc97bc62c369fc49c96ded52f7',
      },
      'common-deep-research': {
        packageSha256: '29c2950041fac0f2e3249d764a248b4989e654327dc3eb35f3ff6ecb0d18e6c5',
        contentSha256: 'aed68420a5e11fb0e22a1cc9f724edb19c471e3aca5b76bc28e4c8b72c7a769d',
        inventorySha256: '050264864308cccffec5ce398de1e6a5d0ee8f41eec8df604334ccb285198de4',
        treeSha256: '7c863d9df147fad3d5e6e8979ab469509144310b6ed8e632278b864b85a1b750',
      },
      'front-design': {
        packageSha256: '27397cc781cba7980aaabb23a2225623f674f9b843830e2cbe86a1fdefa403c7',
        contentSha256: '33d9198678be2f040ea0fd7fa1fed2c43860408351c0a98b50c3aa55f842a4f5',
        inventorySha256: '050264864308cccffec5ce398de1e6a5d0ee8f41eec8df604334ccb285198de4',
        treeSha256: '1d82db71eca6b81f5e6a68c0bef9595b204b111117d7ece4c0d08fe7c05960d8',
      },
    },
  },
  {
    roleType: 'common-content-operator',
    roleTemplateVersionId: '33000000-0000-4000-8000-000000000019',
    sourceDirectory: process.argv[10],
    expected: {
      'account-positioning': {
        packageSha256: '840495a98009df8621453db3bdf94e3f404899efb8e4615bdc77959c2989b08c',
        contentSha256: '75e41dc03369cadff286ab0f2e8501ac1098d96d544930025e7bc668f7d198ce',
        inventorySha256: '050264864308cccffec5ce398de1e6a5d0ee8f41eec8df604334ccb285198de4',
        treeSha256: 'ae851d980a1b775cab9348b7c03fa236bc6be1e174dc0102564f31e2103574f6',
      },
      'brand-compliance-review': {
        packageSha256: '3a37ef337fa51ff51b645ad68695a66629f1d94cc089d9777048dfb374289446',
        contentSha256: 'fa93f100e3fbaa399efa6e8bd45be1fdd0ab4b87714586bb928e097b0a24eab8',
        inventorySha256: '050264864308cccffec5ce398de1e6a5d0ee8f41eec8df604334ccb285198de4',
        treeSha256: '04bb9aca3a1875adaf94dfadb2670fdafb109c60376971eda00756f67c04e2ee',
      },
      'community-engagement': {
        packageSha256: 'f9ff70b4a586a4a6d09188aa6d334daa66873f402396505eba36d62419ff5e11',
        contentSha256: '8c961cac740f2758b782c35a6b65f1ad6bc54f5413b48e4f0afcf1fc42ba8de2',
        inventorySha256: '050264864308cccffec5ce398de1e6a5d0ee8f41eec8df604334ccb285198de4',
        treeSha256: '4f4923ac5ba859704f9b68efc13c4164ac495e6ee8552eb19ffd6d660599bf3a',
      },
      'content-calendar-management': {
        packageSha256: '411e5b0a65e0424232107ebdd53ac3660c2f81a63d22d84d5a141b758ae29952',
        contentSha256: 'b190754458a6264432df60d9716af80817d9df6f384ae4d4065d0675f11bc6a8',
        inventorySha256: '050264864308cccffec5ce398de1e6a5d0ee8f41eec8df604334ccb285198de4',
        treeSha256: '15f680f9c7de8cc220d82fa011e38e414c422f81b0f6048dcd55dc5d94b4092a',
      },
      'content-performance-analysis': {
        packageSha256: 'c42a4cad35c04698435ab7823a69a8110a051a9e4a0ed82b71a1c0952c5b5d6a',
        contentSha256: 'e8437d37802f7ee996c0bfa1c1d0b18b4d879963a3a86f4ea1722622e950aca2',
        inventorySha256: '050264864308cccffec5ce398de1e6a5d0ee8f41eec8df604334ccb285198de4',
        treeSha256: '65e20637482bd1b7513646e1d6578dc081d2c2cfbb57c0a261e03c256f7222cb',
      },
      'cross-platform-repurposing': {
        packageSha256: 'b3a09b143c93d26d6bab40eff56aa7627d713c984f8282377ba2d85786f250ec',
        contentSha256: 'e3ae1a02c8a7e2af7469fbc780d7a85e6c0b11b14d772b46e9380e91d8743a1a',
        inventorySha256: '050264864308cccffec5ce398de1e6a5d0ee8f41eec8df604334ccb285198de4',
        treeSha256: '7b24297b2ad2925cb9e6b51dfc02e8f15d6cabf072795ca938fa1948b480bd81',
      },
      'trend-content-planning': {
        packageSha256: 'e83205c742d4682bc38e637216200e1f5bcab22bbfe6f8de9d96842ba7e54385',
        contentSha256: 'a46a63104b04d3ec2c6f29d34ee01a120f20c32b19740b55070a7c59ac408b9a',
        inventorySha256: '050264864308cccffec5ce398de1e6a5d0ee8f41eec8df604334ccb285198de4',
        treeSha256: 'd51c3b04212d53417a1105f7e759ed3c4c5e2f4cf514755df26672a583bf59f9',
      },
      'visual-content-brief': {
        packageSha256: '82a294d6905df274c3b0fd17bb6c72614b66f697ecc65290c49641a1272b4c2f',
        contentSha256: '60ca7e1b1c02f1877fbc006f20cda0f19dc189868293152a44189e54d4dfd571',
        inventorySha256: '050264864308cccffec5ce398de1e6a5d0ee8f41eec8df604334ccb285198de4',
        treeSha256: 'edd2c40635898bbb6d609a97366559d72caf4ba8dcf18e2b2c4f4434080c5bd4',
      },
      'xiaohongshu-note-creation': {
        packageSha256: 'c6cfabfa4ea3e4db6831b3b667616e81e320bc7ebb79b4aa8ca6fd4912f18fe6',
        contentSha256: 'e2f80f6233fb7816568e26a5a4e90b76e8deb2c9befdcd3b4e1fab48b8898681',
        inventorySha256: '050264864308cccffec5ce398de1e6a5d0ee8f41eec8df604334ccb285198de4',
        treeSha256: '574c4fa6a7fd5ad591e58a567bd034b004241b97dd508950e94d37aae38df185',
      },
      'xiaohongshu-publishing': {
        packageSha256: '34457cf8630bf8ec4e41b8d123477b87c5ecdc08969244c0818faa72417d4401',
        contentSha256: 'b2ba1a305f55ece2b340df748a0048988a8f22a5cc8b148366f4088564e843ae',
        inventorySha256: '050264864308cccffec5ce398de1e6a5d0ee8f41eec8df604334ccb285198de4',
        treeSha256: 'a800ca3f0a621d141032baeefdd0122fb5de5b73add5ae88bb47a3397cec714d',
      },
    },
  },
];

const sha256 = (value) => createHash('sha256').update(value).digest('hex');
const catalog = JSON.parse(readFileSync(catalogPath, 'utf8')).data;

async function readPackage(role, name) {
  if (role.sourceDirectory) return readFileSync(join(role.sourceDirectory, `${name}.zip`));
  const catalogSkills = JSON.parse(catalog[role.roleType].skill);
  const catalogSkill = catalogSkills.find((skill) => skill.name === name);
  if (!catalogSkill) throw new Error(`missing official catalog Skill: ${role.roleType}/${name}`);
  const response = await fetch(catalogSkill.installUrl);
  if (!response.ok) throw new Error(`failed to download ${role.roleType}/${name}: HTTP ${response.status}`);
  return Buffer.from(await response.arrayBuffer());
}

function parsePackage(role, name, bytes) {
  const expected = role.expected[name];
  if (sha256(bytes) !== expected.packageSha256)
    throw new Error(`package digest changed: ${role.roleType}/${name}`);
  const prefix = `${name}/`;
  const archive = unzipSync(bytes);
  const inventoryEntries = new Set();
  const files = [];
  for (const [sourcePath, body] of Object.entries(archive)) {
    if (sourcePath === name || sourcePath === prefix) continue;
    if (!sourcePath.startsWith(prefix))
      throw new Error(`package path escaped root: ${role.roleType}/${name}:${sourcePath}`);
    const relativePath = sourcePath.slice(prefix.length);
    if (!relativePath) continue;
    const path = relativePath.toLocaleLowerCase('en-US') === 'skill.md' ? 'SKILL.md' : relativePath;
    inventoryEntries.add(path);
    const segments = path.replace(/\/$/u, '').split('/');
    for (let index = 1; index < segments.length; index += 1) {
      inventoryEntries.add(`${segments.slice(0, index).join('/')}/`);
    }
    if (!path.endsWith('/')) files.push({ path, bytes: body });
  }
  const inventory = [...inventoryEntries].sort();
  files.sort((left, right) => (left.path < right.path ? -1 : left.path > right.path ? 1 : 0));
  const manifest = files.find((file) => file.path === 'SKILL.md');
  if (!manifest) throw new Error(`manifest missing: ${role.roleType}/${name}`);
  const tree = files.map((file) => ({
    path: file.path,
    bytes: file.bytes.byteLength,
    sha256: sha256(file.bytes),
  }));
  if (sha256(manifest.bytes) !== expected.contentSha256)
    throw new Error(`manifest changed: ${role.roleType}/${name}`);
  if (sha256(JSON.stringify(inventory)) !== expected.inventorySha256)
    throw new Error(`inventory changed: ${role.roleType}/${name}`);
  if (sha256(JSON.stringify(tree)) !== expected.treeSha256)
    throw new Error(`file tree changed: ${role.roleType}/${name}`);
  return {
    id: `${role.roleType}/${name}`,
    roleTemplateVersionId: role.roleTemplateVersionId,
    name,
    fileName: `${name}.zip`,
    mediaType: 'application/zip',
    sizeBytes: bytes.byteLength,
    packageSha256: expected.packageSha256,
    contentSha256: expected.contentSha256,
    inventory,
    fileSha256: Object.fromEntries(tree.map((file) => [file.path, file.sha256])),
    base64: bytes.toString('base64'),
  };
}

const packages = [];
for (const role of ROLES) {
  for (const name of Object.keys(role.expected)) {
    packages.push(parsePackage(role, name, await readPackage(role, name)));
  }
}

const literal = (value) => JSON.stringify(value, null, 2);
const constantName = ({ id }) => `${id.replaceAll(/[^a-z0-9]/giu, '_').toUpperCase()}_BASE64`;
const base64Constants = packages
  .map((skillPackage) => {
    const chunks = skillPackage.base64.match(/.{1,120}/gu) ?? [];
    return `const ${constantName(skillPackage)} = [\n${chunks
      .map((chunk) => `  ${JSON.stringify(chunk)},`)
      .join('\n')}\n].join('');`;
  })
  .join('\n\n');
const ids = packages.map(({ id }) => JSON.stringify(id)).join(' | ');
const descriptors = packages
  .map((skillPackage) => {
    const metadata = Object.fromEntries(Object.entries(skillPackage).filter(([key]) => key !== 'base64'));
    const base64Constant = constantName(skillPackage);
    return literal({ ...metadata, base64: `__${base64Constant}__` }).replace(
      JSON.stringify(`__${base64Constant}__`),
      base64Constant,
    );
  })
  .join(',\n');

const output = `// GENERATED FILE - do not edit by hand.
// Source: retained official Frontend Developer, Product Manager, Project Administrator, UI Designer, QA Engineer, DevOps Engineer, Operations Engineer, Data Analyst and Content Operations Specialist catalog ZIPs, verified 2026-08-26.
// Regenerate with: node scripts/generate-official-preset-skill-packages.mjs [frontend-snapshot] [product-manager-snapshot] [project-administrator-snapshot] [ui-designer-snapshot] [qa-engineer-snapshot] [devops-engineer-snapshot] [operations-engineer-snapshot] [data-analyst-snapshot] [content-operations-snapshot]

import type { OfficialSkillPackage } from './official-skill-package.ts';

export type OfficialPresetSkillPackageId = ${ids};

export interface OfficialPresetSkillPackage extends OfficialSkillPackage<OfficialPresetSkillPackageId> {
  readonly roleTemplateVersionId: string;
  readonly name: string;
}

${base64Constants}

const PACKAGES: readonly (Omit<OfficialPresetSkillPackage, 'bytes'> & { readonly base64: string })[] = [
${descriptors}
];

function materialize(
  descriptor: Omit<OfficialPresetSkillPackage, 'bytes'> & { readonly base64: string },
): OfficialPresetSkillPackage {
  const { base64, ...metadata } = descriptor;
  return { ...metadata, bytes: () => Buffer.from(base64, 'base64') };
}

export function officialPresetSkillPackage(
  roleTemplateVersionId: string | null,
  name: string,
): OfficialPresetSkillPackage | undefined {
  const descriptor = PACKAGES.find(
    (candidate) => candidate.roleTemplateVersionId === roleTemplateVersionId && candidate.name === name,
  );
  return descriptor ? materialize(descriptor) : undefined;
}

export function officialPresetSkillPackageById(id: string): OfficialPresetSkillPackage | undefined {
  const descriptor = PACKAGES.find((candidate) => candidate.id === id);
  return descriptor ? materialize(descriptor) : undefined;
}
`;

writeFileSync(outputPath, output);
console.log(`wrote ${outputPath} with ${packages.length} exact packages`);
