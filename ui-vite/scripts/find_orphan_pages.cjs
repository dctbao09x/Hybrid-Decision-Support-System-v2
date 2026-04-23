#!/usr/bin/env node
/**
 * Orphan Pages Detection Script
 * ==============================
 * 
 * Scans src/pages/ and compares against App.jsx routes
 * to find pages without active routes.
 * 
 * Usage: npm run audit:routes
 */

const fs = require('fs');
const path = require('path');

const SRC_DIR = path.join(__dirname, '..', 'src');
const PAGES_DIR = path.join(SRC_DIR, 'pages');
const APP_FILE = path.join(SRC_DIR, 'App.jsx');

// Colors for terminal output
const colors = {
  reset: '\x1b[0m',
  red: '\x1b[31m',
  green: '\x1b[32m',
  yellow: '\x1b[33m',
  cyan: '\x1b[36m',
  bold: '\x1b[1m',
};

function log(message, color = 'reset') {
  console.log(`${colors[color]}${message}${colors.reset}`);
}

// Folders to ignore (components, not pages)
const IGNORE_FOLDERS = ['tabs', 'components', 'hooks', 'utils', '__tests__', 'styles'];

/**
 * Recursively find all page components
 */
function findPages(dir, pages = [], depth = 0) {
  if (!fs.existsSync(dir)) return pages;
  
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  
  for (const entry of entries) {
    const fullPath = path.join(dir, entry.name);
    
    if (entry.isDirectory()) {
      // Skip component/utility folders
      if (IGNORE_FOLDERS.includes(entry.name.toLowerCase())) {
        continue;
      }
      
      // Check for index file or component file
      const indexFiles = ['index.js', 'index.jsx', 'index.ts', 'index.tsx'];
      const hasIndex = indexFiles.some(f => fs.existsSync(path.join(fullPath, f)));
      
      const componentFiles = fs.readdirSync(fullPath).filter(f => 
        /\.(jsx|tsx)$/.test(f) && !f.startsWith('index')
      );
      
      if (hasIndex || componentFiles.length > 0) {
        const relativePath = path.relative(PAGES_DIR, fullPath);
        pages.push({
          name: entry.name,
          path: relativePath,
          fullPath: fullPath,
          hasIndex,
          components: componentFiles,
        });
      }
      
      // Recurse into subdirectories (max depth 3)
      if (depth < 3) {
        findPages(fullPath, pages, depth + 1);
      }
    }
  }
  
  return pages;
}

/**
 * Extract routes from App.jsx
 */
function extractRoutes(appContent) {
  const routes = [];
  
  // Match <Route path="..." element={...} />
  const routeRegex = /<Route\s+path=["']([^"']+)["']\s+element=\{<(\w+)/g;
  let match;
  
  while ((match = routeRegex.exec(appContent)) !== null) {
    routes.push({
      path: match[1],
      component: match[2],
    });
  }
  
  // Also match element before path
  const routeRegex2 = /<Route\s+element=\{<(\w+)[^}]*}\s+path=["']([^"']+)["']/g;
  while ((match = routeRegex2.exec(appContent)) !== null) {
    routes.push({
      path: match[2],
      component: match[1],
    });
  }
  
  return routes;
}

/**
 * Extract imports from App.jsx
 */
function extractImports(appContent) {
  const imports = new Map();
  
  // Match: import X from './pages/Y/Z'
  const importRegex = /import\s+(?:{?\s*(\w+)\s*}?|(\w+))\s+from\s+['"]\.\/pages\/([^'"]+)['"]/g;
  let match;
  
  while ((match = importRegex.exec(appContent)) !== null) {
    const component = match[1] || match[2];
    const pagePath = match[3];
    imports.set(component, pagePath);
  }
  
  // Match lazy imports
  const lazyRegex = /const\s+(\w+)\s*=\s*lazy\(\s*\(\)\s*=>\s*import\(['"]\.\/pages\/([^'"]+)['"]\)/g;
  while ((match = lazyRegex.exec(appContent)) !== null) {
    imports.set(match[1], match[2]);
  }
  
  return imports;
}

/**
 * Main execution
 */
function main() {
  log('\n========================================', 'cyan');
  log('  Orphan Pages Detection Report', 'bold');
  log('========================================\n', 'cyan');

  // Find all pages
  const pages = findPages(PAGES_DIR);
  log(`Found ${pages.length} page directories\n`, 'cyan');

  // Read App.jsx
  if (!fs.existsSync(APP_FILE)) {
    log('ERROR: App.jsx not found!', 'red');
    process.exit(1);
  }
  
  const appContent = fs.readFileSync(APP_FILE, 'utf-8');
  const routes = extractRoutes(appContent);
  const imports = extractImports(appContent);
  
  log(`Found ${routes.length} routes in App.jsx`, 'cyan');
  log(`Found ${imports.size} page imports\n`, 'cyan');

  // Find orphans
  const orphans = [];
  const routed = [];
  
  for (const page of pages) {
    // Check if page is imported
    let isImported = false;
    for (const [component, importPath] of imports) {
      if (importPath.includes(page.name)) {
        isImported = true;
        break;
      }
    }
    
    // Check if page appears in any route
    let hasRoute = false;
    for (const route of routes) {
      if (imports.get(route.component)?.includes(page.name)) {
        hasRoute = true;
        break;
      }
    }
    
    if (!isImported || !hasRoute) {
      orphans.push(page);
    } else {
      routed.push(page);
    }
  }

  // Report routed pages
  log('✅ ROUTED PAGES:', 'green');
  for (const page of routed) {
    log(`   ${page.path}`, 'green');
  }

  // Report orphans
  if (orphans.length > 0) {
    log('\n⚠️  ORPHAN PAGES (no route):', 'yellow');
    for (const page of orphans) {
      log(`   ${page.path}`, 'yellow');
    }
  } else {
    log('\n✅ No orphan pages found!', 'green');
  }

  // Commented routes check - only match actual commented <Route> elements
  // Pattern: {/* <Route ... /> */} (entire route is commented out)
  const commentedRoutes = appContent.match(/{\s*\/\*\s*<Route[^}]+\/>\s*\*\/\s*}/g) || [];
  const commentedRoutesAlt = appContent.match(/\/\/\s*<Route[^\n]*/g) || [];
  
  if (commentedRoutes.length > 0 || commentedRoutesAlt.length > 0) {
    log('\n⚠️  COMMENTED ROUTES:', 'yellow');
    for (const r of [...commentedRoutes, ...commentedRoutesAlt]) {
      log(`   ${r.substring(0, 60)}...`, 'yellow');
    }
  }

  // Summary
  log('\n========================================', 'cyan');
  log('  SUMMARY', 'bold');
  log('========================================', 'cyan');
  log(`Total pages:     ${pages.length}`);
  log(`Routed pages:    ${routed.length}`, 'green');
  log(`Orphan pages:    ${orphans.length}`, orphans.length > 0 ? 'yellow' : 'green');
  log(`Route coverage:  ${((routed.length / pages.length) * 100).toFixed(1)}%`);
  
  // Exit with error if orphans found
  if (orphans.length > 0) {
    log('\n❌ FAIL: Orphan pages detected', 'red');
    process.exit(1);
  } else {
    log('\n✅ PASS: All pages have routes', 'green');
    process.exit(0);
  }
}

main();
