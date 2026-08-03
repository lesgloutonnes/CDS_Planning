// ================================
// DIAGNOSTIC DU MENU CONTEXTUEL - VERSION DEBUG
// ================================

/* ================================
   VARIABLES GLOBALES AVEC DEBUG
   ================================ */

let contextMenu = null;
let contextMenuTarget = null;

/* ================================
   INITIALISATION AVEC DIAGNOSTICS
   ================================ */

document.addEventListener('DOMContentLoaded', function() {
    // Attendre que le planning soit chargé
    setTimeout(() => {
        initializeContextMenuWithDebug();
    }, 500);
    
    // Essayer aussi après 2 secondes au cas où
    setTimeout(() => {
        if (!contextMenu) {
            initializeContextMenuWithDebug();
        }
    }, 2000);
});

function initializeContextMenuWithDebug() {
    // 1. Vérifier les cellules
    const cells = document.querySelectorAll('.assignment-cell');
    
    if (cells.length === 0) {
        return false;
    }
    
    // 2. Créer le menu contextuel
    const menuCreated = createContextMenuWithDebug();
    
    if (!menuCreated) {
        return false;
    }
    
    // 3. Ajouter les événements
    cells.forEach((cell) => {
        try {
            // Supprimer l'ancien event listener s'il existe
            cell.removeEventListener('contextmenu', handleContextMenuDebug);
            
            // Ajouter le nouvel event listener
            cell.addEventListener('contextmenu', handleContextMenuDebug, true);
        } catch (error) {
            // Ignorer les erreurs silencieusement
        }
    });
    
    // 4. Ajouter les événements de fermeture
    document.addEventListener('click', closeContextMenuDebug, true);
    document.addEventListener('scroll', closeContextMenuDebug, true);
    
    return true;
}

function createContextMenuWithDebug() {
    try {
        // Supprimer l'ancien menu s'il existe
        if (contextMenu) {
            contextMenu.remove();
            contextMenu = null;
        }
        
        contextMenu = document.createElement('div');
        contextMenu.className = 'context-menu-chc';
        contextMenu.style.cssText = `
            position: fixed;
            background: white;
            border: 2px solid #d1d5db;
            border-radius: 12px;
            box-shadow: 0 8px 25px rgba(30, 58, 138, 0.2);
            z-index: 10000;
            min-width: 300px;
            max-width: 420px;
            display: none;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            overflow: hidden;
        `;
        
        contextMenu.innerHTML = `
            <div class="context-menu-header-chc" style="
                background: #1e3a8a;
                color: white;
                padding: 14px 18px;
                font-weight: 600;
                font-size: 0.9rem;
            ">
                <span class="context-menu-title-chc">Actions disponibles</span>
            </div>
            <div class="context-menu-content-chc" style="padding: 8px 0;">
                <div class="context-menu-loading-chc" style="
                    padding: 20px;
                    text-align: center;
                    color: #6b7280;
                    font-style: italic;
                ">
                    <i class="fa fa-spinner fa-spin" style="margin-right: 8px; color: #1e3a8a;"></i> 
                    Chargement...
                </div>
            </div>
        `;
        
        document.body.appendChild(contextMenu);
        
        return true;
    } catch (error) {
        return false;
    }
}

/* ================================
   GESTIONNAIRE D'ÉVÉNEMENTS AVEC DEBUG
   ================================ */

function handleContextMenuDebug(e) {
    // Empêcher le menu contextuel par défaut
    e.preventDefault();
    e.stopPropagation();
    e.stopImmediatePropagation();
    
    const cell = e.currentTarget;
    const assignmentCode = cell.querySelector('.assignment-code');
    
    contextMenuTarget = {
        cell: cell,
        assignmentCode: assignmentCode,
        isEmpty: !assignmentCode,
        position: getCellPositionDebug(cell)
    };
    
    // Afficher le menu
    showContextMenuDebug(e.pageX, e.pageY);
    
    return false;
}

function showContextMenuDebug(x, y) {
    if (!contextMenu) {
        return;
    }
    
    // Positionner temporairement le menu hors écran pour mesurer sa taille
    contextMenu.style.display = 'block';
    contextMenu.style.visibility = 'hidden';
    contextMenu.style.left = '-9999px';
    contextMenu.style.top = '-9999px';
    contextMenu.style.zIndex = '10000';
    
    // Mesurer la taille du menu
    const rect = contextMenu.getBoundingClientRect();
    const windowWidth = window.innerWidth;
    const windowHeight = window.innerHeight;
    const menuWidth = rect.width;
    const menuHeight = rect.height;
    
    // Calculer la position optimale
    let finalX = x;
    let finalY = y;
    
    // Ajuster horizontalement si nécessaire
    if (x + menuWidth > windowWidth) {
        finalX = Math.max(10, x - menuWidth);
    }
    
    // Ajuster verticalement si nécessaire (priorité : afficher vers le haut si pas assez d'espace en bas)
    if (y + menuHeight > windowHeight) {
        // Vérifier s'il y a plus d'espace en haut qu'en bas
        const spaceBelow = windowHeight - y;
        const spaceAbove = y;
        
        if (spaceAbove >= menuHeight || spaceAbove > spaceBelow) {
            // Afficher vers le haut
            finalY = Math.max(10, y - menuHeight);
        } else {
            // Afficher vers le haut mais limiter à la hauteur disponible
            finalY = Math.max(10, windowHeight - menuHeight - 10);
        }
    }
    
    // Positionner et rendre visible
    contextMenu.style.left = finalX + 'px';
    contextMenu.style.top = finalY + 'px';
    contextMenu.style.visibility = 'visible';
}

function closeContextMenuDebug() {
    if (contextMenu) {
        contextMenu.style.display = 'none';
    }
    contextMenuTarget = null;
}

function getCellPositionDebug(cell) {
    const row = cell.closest('tr');
    const cellIndex = Array.from(row.cells).indexOf(cell);
    
    // Déterminer si c'est une cellule journée complète
    const isFullDay = cell.hasAttribute('colspan') && cell.getAttribute('colspan') === '2';
    
    let dayColumnIndex, period;
    
    if (isFullDay) {
        dayColumnIndex = cellIndex - 1;
        period = 'full';
    } else {
        dayColumnIndex = Math.floor((cellIndex - 1) / 2);
        const isAM = (cellIndex - 1) % 2 === 0;
        period = isAM ? 'am' : 'pm';
    }
    
    // Déterminer le site et type de permanence
    const siteCell = row.querySelector('.site-cell');
    let siteCode = 'MLE';
    let siteName = 'Mont Légia';
    let permanenceType = 'ATL';
    
    if (siteCell) {
        const siteFullname = siteCell.querySelector('.site-fullname');
        
        if (siteFullname) {
            siteName = siteFullname.textContent.trim();
            
            // Extraire le code du site depuis le texte (format: "Nom (CODE)")
            const match = siteName.match(/\(([A-Z]+)\)/);
            if (match) {
                siteCode = match[1];
            }
            
            // Déterminer le type de permanence selon le nom
            if (siteName.toLowerCase().includes('on site mle') || siteName.toLowerCase().includes('atelier')) {
                permanenceType = 'ATL';
            } else if (siteName.toLowerCase().includes('fonctionnelle')) {
                permanenceType = 'FCT';
            } else if (siteName.toLowerCase().includes('technique')) {
                permanenceType = 'TCH';
            } else if (siteCode !== 'MLE') {
                permanenceType = 'TCH';
            }
        }
    }
    
    return {
        day_index: Math.max(0, Math.min(4, dayColumnIndex)),
        period: period,
        site_code: siteCode,
        site_name: siteName,
        permanence_type: permanenceType
    };
}

/* ================================
   FONCTIONS DE TEST
   ================================ */

function testContextMenu() {
    const cells = document.querySelectorAll('.assignment-cell');
    
    if (cells.length > 0) {
        const firstCell = cells[0];
        
        // Simuler un clic droit
        const rect = firstCell.getBoundingClientRect();
        const mockEvent = {
            preventDefault: () => {},
            stopPropagation: () => {},
            stopImmediatePropagation: () => {},
            currentTarget: firstCell,
            target: firstCell,
            pageX: rect.left + rect.width / 2,
            pageY: rect.top + rect.height / 2
        };
        
        handleContextMenuDebug(mockEvent);
    }
}

/* ================================
   FONCTIONS UTILITAIRES DE DEBUG
   ================================ */

function debugMenuState() {
    return {
        menuExists: !!contextMenu,
        menuDisplay: contextMenu ? contextMenu.style.display : null,
        menuPosition: contextMenu ? {
            left: contextMenu.style.left,
            top: contextMenu.style.top,
            zIndex: contextMenu.style.zIndex
        } : null,
        menuInDOM: contextMenu ? document.body.contains(contextMenu) : false,
        targetExists: !!contextMenuTarget
    };
}

function forceShowMenu() {
    if (!contextMenu) {
        createContextMenuWithDebug();
    }
    
    if (contextMenu) {
        contextMenu.style.display = 'block';
        contextMenu.style.left = '100px';
        contextMenu.style.top = '100px';
        contextMenu.style.zIndex = '10000';
    }
}

// Exposer les fonctions de debug globalement
window.debugMenuState = debugMenuState;
window.forceShowMenu = forceShowMenu;
window.testContextMenu = testContextMenu;
window.initializeContextMenuWithDebug = initializeContextMenuWithDebug;