// planning_visual_combined.js - Version unifiée avec menu contextuel et drag&drop
// ===============================================================================

/* ================================
   VARIABLES GLOBALES
   ================================ */

   let dragSource = null;
   let contextMenu = null;
   let contextMenuTarget = null;
   let employeeSkinMap = {};
   
   // Système de rollback et file d'attente pour améliorer la robustesse
   let operationQueue = [];
   let isProcessingOperation = false;
   let lastOperationState = null; // État sauvegardé avant modification pour rollback
   let dragAndDropListeners = new WeakMap(); // Pour éviter les listeners dupliqués
   
   /* ================================
      AUTO-REFRESH SUR INACTIVITÉ (ÉCRAN TV)
      - Si aucune activité (mousemove, scroll, clavier, etc.) pendant 30s:
        - se placer sur la semaine en cours (via endpoint serveur)
        - puis rafraîchir la vue
      ================================ */
   
   function initializeIdleAutoRefresh() {
       const LOG_PREFIX = '[IdleAutoRefresh]';
       const INACTIVITY_MS = 30000; // 30s
       const RESCHEDULE_AFTER_BLOCK_MS = 5000; // si menu/drag, retenter plus tard

       // L'autorisation est calculée côté serveur et injectée dans la page.
       const canAutoRefresh = (
           window.CAN_IDLE_AUTO_REFRESH === true
           || window.CAN_IDLE_AUTO_REFRESH === 'true'
           || window.CAN_IDLE_AUTO_REFRESH === 1
           || window.CAN_IDLE_AUTO_REFRESH === '1'
       );
       if (!canAutoRefresh) {
           console.log(`${LOG_PREFIX} disabled`, {
               reason: 'not_allowed_by_server',
           });
           return; // Ne pas initialiser le refresh pour les autres utilisateurs
       }

       let inactivityTimeout = null;
       let lastActivityLogTs = 0;

       console.log(`${LOG_PREFIX} init`, {
           inactivity_ms: INACTIVITY_MS,
           reschedule_after_block_ms: RESCHEDULE_AFTER_BLOCK_MS,
           user: window.USER_LOGIN || '',
           pathname: window.location.pathname,
           search: window.location.search,
       });
   
       function isPlanningPage() {
           return /\/(?:web\/)?planning\/\d+/.test(window.location.pathname);
       }
   
       function isEmbeddedMode() {
           try {
               if (window.IS_EMBEDDED === true || window.IS_EMBEDDED === "true" || window.IS_EMBEDDED === 1 || window.IS_EMBEDDED === "1") {
                   return true;
               }
               if (new URLSearchParams(window.location.search).get('embedded') === '1') {
                   return true;
               }
               return window.self !== window.top;
           } catch (e) {
               return false;
           }
       }
   
       function buildPlanningUrl(planningId) {
           const base = window.location.pathname.startsWith('/web/') ? '/web/planning/' : '/planning/';
           return base + planningId + (isEmbeddedMode() ? '?embedded=1' : '');
       }
   
       function schedule(ms) {
           if (inactivityTimeout) {
               clearTimeout(inactivityTimeout);
           }
           console.log(`${LOG_PREFIX} schedule`, { in_ms: ms });
           inactivityTimeout = setTimeout(onIdle, ms);
       }
   
       function noteActivity(e) {
           // Chaque activité repousse le prochain refresh
           const now = Date.now();
           // Throttle logs pour éviter de spam (ex: mousemove)
           if (now - lastActivityLogTs > 2000) {
               lastActivityLogTs = now;
               console.log(`${LOG_PREFIX} activity`, { type: e && e.type ? e.type : 'unknown' });
           }
           schedule(INACTIVITY_MS);
       }
   
       async function fetchCurrentWeekPlanningId() {
           console.log(`${LOG_PREFIX} api call`, { url: '/planning/get_current_week_planning' });
           const payload = {
               jsonrpc: "2.0",
               method: "call",
               params: {},
               id: Math.floor(Math.random() * 1000000),
           };
   
           const response = await fetch('/planning/get_current_week_planning', {
               method: 'POST',
               headers: {
                   'Content-Type': 'application/json',
                   'X-Requested-With': 'XMLHttpRequest',
               },
               body: JSON.stringify(payload),
           });
   
           console.log(`${LOG_PREFIX} api response`, { status: response.status, ok: response.ok });
   
           const result = await response.json();
           const actualResult = result.result || result;
           console.log(`${LOG_PREFIX} api payload`, actualResult);
           if (actualResult && actualResult.success && actualResult.planning_id) {
               return parseInt(actualResult.planning_id);
           }
           return null;
       }
   
       async function onIdle() {
           console.log(`${LOG_PREFIX} idle fired`);
           // Si l’onglet n’est pas visible, on n’insiste pas
           if (document.hidden) {
               console.log(`${LOG_PREFIX} blocked`, { reason: 'document.hidden' });
               schedule(INACTIVITY_MS);
               return;
           }
   
           // Ne rien faire si on n’est pas sur la vue planning
           if (!isPlanningPage()) {
               console.log(`${LOG_PREFIX} blocked`, { reason: 'not planning page', pathname: window.location.pathname });
               schedule(INACTIVITY_MS);
               return;
           }
   
           // Ne pas rafraîchir si menu contextuel ouvert
           if (contextMenu && contextMenu.style.display === 'block') {
               console.log(`${LOG_PREFIX} blocked`, { reason: 'context menu open' });
               schedule(RESCHEDULE_AFTER_BLOCK_MS);
               return;
           }
   
           // Ne pas rafraîchir si drag en cours
           if (dragSource !== null) {
               console.log(`${LOG_PREFIX} blocked`, { reason: 'drag in progress' });
               schedule(RESCHEDULE_AFTER_BLOCK_MS);
               return;
           }
   
           try {
               const currentPlanningId = getPlanningId();
               const currentWeekPlanningId = await fetchCurrentWeekPlanningId();
               console.log(`${LOG_PREFIX} compare`, { currentPlanningId, currentWeekPlanningId });
   
               if (currentWeekPlanningId && currentPlanningId && currentWeekPlanningId !== currentPlanningId) {
                   const target = buildPlanningUrl(currentWeekPlanningId);
                   console.log(`${LOG_PREFIX} redirect`, { to: target });
                   window.location.href = target;
                   return;
               }
   
               // Déjà sur la bonne semaine (ou fallback): rafraîchir la vue
               console.log(`${LOG_PREFIX} reload`, { reason: 'same week or missing id' });
               location.reload();
           } catch (e) {
               // En cas d’erreur réseau, fallback sur un reload simple
               console.error(`${LOG_PREFIX} error`, e);
               console.log(`${LOG_PREFIX} reload`, { reason: 'error fallback' });
               location.reload();
           }
       }
   
       const activityEvents = [
           'mousemove',
           'mousedown',
           'mouseup',
           'wheel',
           'scroll',
           'keydown',
           'touchstart',
           'touchmove',
           'click',
           'contextmenu',
       ];
   
       activityEvents.forEach(eventType => {
           document.addEventListener(eventType, noteActivity, { passive: true });
       });
   
       document.addEventListener('visibilitychange', () => {
           // Quand l’onglet redevient visible, repartir sur un cycle complet
           if (!document.hidden) {
               console.log(`${LOG_PREFIX} visibilitychange`, { hidden: false });
               schedule(INACTIVITY_MS);
           } else {
               console.log(`${LOG_PREFIX} visibilitychange`, { hidden: true });
           }
       });
   
       // Démarrer le cycle
       schedule(INACTIVITY_MS);
   
       // Nettoyage
       window.addEventListener('beforeunload', function () {
           if (inactivityTimeout) {
               clearTimeout(inactivityTimeout);
           }
       });
   }
   
   /* ================================
      INITIALISATION PRINCIPALE
      ================================ */
   
   document.addEventListener('DOMContentLoaded', function () {
       // 1. Nettoyer la file d'attente au cas où (si rechargement de page)
       operationQueue = [];
       isProcessingOperation = false;
       lastOperationState = null;
   
       // 2. Appliquer les couleurs
       applyEmployeeColors();
       fetchEmployeeSkinsAndApply();
   
       // 3. Initialiser le drag & drop
       initializeDragAndDrop();
   
       // 4. Initialiser les boutons
       initializeButtons();
   
       // 5. Initialiser le menu contextuel avec délai
       setTimeout(() => {
           initializeContextMenu();
           handleContextMenuConflicts();
       }, 500);
   
       // 6. Vérifications et panel de contrôle
       setTimeout(() => {
           ensureContextMenuIntegration();
       }, 1500);
   
       // 7. Auto-refresh en cas d'inactivité (écran TV)
       initializeIdleAutoRefresh();
   });
   
   // Nettoyer la file d'attente avant de quitter la page
   window.addEventListener('beforeunload', function () {
       operationQueue = [];
       isProcessingOperation = false;
   });
   
   /* ================================
   SYSTÈME DE COULEURS EMPLOYÉS
   ================================ */
   
   function applyEmployeeColors() {
       const assignmentCodes = document.querySelectorAll('.assignment-code');
   
       assignmentCodes.forEach(function (element) {
           let colorValue = parseInt(element.getAttribute('data-color'), 10);
           if (!Number.isInteger(colorValue) || colorValue < 0) {
               colorValue = 0;
               // Normaliser l'attribut pour les traitements suivants (drag/drop, debug, etc.)
               element.setAttribute('data-color', '0');
           }
           const colors = getEmployeeColors(colorValue);
   
           element.style.backgroundColor = colors.background;
           element.style.borderColor = colors.border;
           element.style.color = colors.text;
           element.style.boxShadow = colors.shadow;
           applyEmployeeSkin(element);
       });
   }

   function applyEmployeeSkin(element) {
       if (!element) {
           return;
       }

       element.classList.remove('skin-sakura');
       element.classList.remove('skin-johnny-wolf-moon');
       element.classList.remove('skin-birthday-party');
       element.classList.remove('skin-carni');
       const employeeId = element.getAttribute('data-employee-id');
       if (!employeeId) {
           return;
       }

       const skinInfo = employeeSkinMap[String(employeeId)];
       if (!skinInfo || !skinInfo.enabled) {
           return;
       }

       if (skinInfo.type === 'sakura') {
           element.classList.add('skin-sakura');
       } else if (skinInfo.type === 'johnny_wolf_moon') {
           element.classList.add('skin-johnny-wolf-moon');
       } else if (skinInfo.type === 'birthday_party') {
           element.classList.add('skin-birthday-party');
       } else if (skinInfo.type === 'carni') {
           element.classList.add('skin-carni');
       }
   }

   function fetchEmployeeSkinsAndApply() {
       const assignmentCodes = document.querySelectorAll('.assignment-code[data-employee-id]');
       if (!assignmentCodes.length) {
           employeeSkinMap = {};
           return;
       }

       const employeeIds = Array.from(
           new Set(
               Array.from(assignmentCodes)
                   .map(element => parseInt(element.getAttribute('data-employee-id'), 10))
                   .filter(id => Number.isInteger(id) && id > 0)
           )
       );

       if (!employeeIds.length) {
           employeeSkinMap = {};
           applyEmployeeColors();
           return;
       }

       const payload = {
           jsonrpc: "2.0",
           method: "call",
           params: {
               model: "hr.employee",
               method: "read",
               args: [employeeIds, ["skin_enabled", "skin_type"]],
               kwargs: {},
           },
           id: Math.floor(Math.random() * 1000000),
       };

       fetch('/web/dataset/call_kw/hr.employee/read', {
           method: 'POST',
           headers: {
               'Content-Type': 'application/json',
               'X-Requested-With': 'XMLHttpRequest'
           },
           body: JSON.stringify(payload)
       })
           .then(response => response.json())
           .then(result => {
               const actualResult = result.result || result;
               if (!Array.isArray(actualResult)) {
                   employeeSkinMap = {};
                   applyEmployeeColors();
                   return;
               }

               const skins = {};
               actualResult.forEach(employee => {
                   if (!employee || !employee.id) {
                       return;
                   }
                   skins[String(employee.id)] = {
                       enabled: Boolean(employee.skin_enabled),
                       type: employee.skin_type || '',
                   };
               });

               employeeSkinMap = skins;
               applyEmployeeColors();
           })
           .catch(() => {
               employeeSkinMap = {};
               applyEmployeeColors();
           });
   }
   
   function getEmployeeColors(colorIndex) {
       const colors = [
           { background: '#fbbf24', border: '#f59e0b', text: '#1f2937', shadow: '0 2px 4px rgba(251, 191, 36, 0.3)' },  // Jaune
           { background: '#ef4444', border: '#dc2626', text: 'white', shadow: '0 2px 4px rgba(239, 68, 68, 0.3)' },     // Rouge
           { background: '#10b981', border: '#059669', text: 'white', shadow: '0 2px 4px rgba(16, 185, 129, 0.3)' },    // Vert
           { background: '#3b82f6', border: '#2563eb', text: 'white', shadow: '0 2px 4px rgba(59, 130, 246, 0.3)' },    // Bleu
           { background: '#8b5cf6', border: '#7c3aed', text: 'white', shadow: '0 2px 4px rgba(139, 92, 246, 0.3)' },    // Violet
           { background: '#ec4899', border: '#db2777', text: 'white', shadow: '0 2px 4px rgba(236, 72, 153, 0.3)' },    // Rose
           { background: '#f97316', border: '#ea580c', text: 'white', shadow: '0 2px 4px rgba(249, 115, 22, 0.3)' },    // Orange
           { background: '#06b6d4', border: '#0891b2', text: 'white', shadow: '0 2px 4px rgba(6, 182, 212, 0.3)' },     // Turquoise
           { background: '#84cc16', border: '#65a30d', text: 'white', shadow: '0 2px 4px rgba(132, 204, 22, 0.3)' },    // Vert pomme
           { background: '#ff6b6b', border: '#ff5252', text: 'white', shadow: '0 2px 4px rgba(255, 107, 107, 0.3)' },   // Corail
           { background: '#cd7f32', border: '#b87333', text: 'white', shadow: '0 2px 4px rgba(205, 127, 50, 0.3)' },    // Bronze
           { background: '#ffd700', border: '#eab308', text: '#1f2937', shadow: '0 2px 4px rgba(255, 215, 0, 0.3)' },   // Or
           { background: '#7c2d92', border: '#581c87', text: 'white', shadow: '0 2px 4px rgba(124, 45, 146, 0.3)' },    // Prune
           { background: '#a78bfa', border: '#8b5cf6', text: 'white', shadow: '0 2px 4px rgba(167, 139, 250, 0.3)' },   // Lavande
           { background: '#fb7185', border: '#f43f5e', text: 'white', shadow: '0 2px 4px rgba(251, 113, 133, 0.3)' },   // Saumon
           { background: '#8b4513', border: '#5c3317', text: 'white', shadow: '0 2px 4px rgba(139, 69, 19, 0.3)' },     // Brun
           { background: '#d946ef', border: '#c026d3', text: 'white', shadow: '0 2px 4px rgba(217, 70, 239, 0.3)' },    // Magenta
           { background: '#243c5a', border: '#1e293b', text: 'white', shadow: '0 2px 4px rgba(36, 60, 90, 0.3)' },      // Bleu nuit
           { background: '#22c55e', border: '#16a34a', text: 'white', shadow: '0 2px 4px rgba(34, 197, 94, 0.3)' },     // Vert forêt
           { background: '#ffe4b5', border: '#fcd29f', text: '#1f2937', shadow: '0 2px 4px rgba(255, 228, 181, 0.3)' }, // Beige
           { background: '#000000', border: '#1f2937', text: 'white', shadow: '0 2px 4px rgba(0, 0, 0, 0.4)' },         // Noir
           { background: '#ffffff', border: '#d1d5db', text: '#1f2937', shadow: '0 2px 4px rgba(0, 0, 0, 0.05)' },      // Blanc
           { background: '#6b7280', border: '#4b5563', text: 'white', shadow: '0 2px 4px rgba(107, 114, 128, 0.3)' },   // Gris foncé
           { background: '#9ca3af', border: '#6b7280', text: 'black', shadow: '0 2px 4px rgba(156, 163, 175, 0.3)' },   // Gris clair
           { background: '#cc7722', border: '#b05e18', text: 'white', shadow: '0 2px 4px rgba(204, 119, 34, 0.3)' },    // Ocre
           { background: '#800020', border: '#4b0014', text: 'white', shadow: '0 2px 4px rgba(128, 0, 32, 0.3)' },      // Bordeaux
           { background: '#98ff98', border: '#7dd87d', text: '#1f2937', shadow: '0 2px 4px rgba(152, 255, 152, 0.3)' }, // Menthe
           { background: '#aec6cf', border: '#8faeb9', text: '#1f2937', shadow: '0 2px 4px rgba(174, 198, 207, 0.3)' }, // Bleu pastel
           { background: '#004e64', border: '#003645', text: 'white', shadow: '0 2px 4px rgba(0, 78, 100, 0.3)' },      // Bleu pétrole
           { background: '#b7410e', border: '#93330b', text: 'white', shadow: '0 2px 4px rgba(183, 65, 14, 0.3)' },     // Rouille
           { background: '#d0f0c0', border: '#b2e0a0', text: '#1f2937', shadow: '0 2px 4px rgba(208, 240, 192, 0.3)' }, // Menthe glaciale
           { background: '#758e67', border: '#5f7353', text: 'white', shadow: '0 2px 4px rgba(117, 142, 103, 0.3)' },  // Vert mousse
           { background: '#f3e5ab', border: '#e6d89c', text: '#1f2937', shadow: '0 2px 4px rgba(243, 229, 171, 0.3)' }, // Crème
           { background: '#c3b091', border: '#a69375', text: '#1f2937', shadow: '0 2px 4px rgba(195, 176, 145, 0.3)' }, // Kaki clair
           { background: '#c0c0c0', border: '#a0a0a0', text: '#1f2937', shadow: '0 2px 4px rgba(192, 192, 192, 0.3)' }, // Argent
           { background: '#b87333', border: '#9c5a27', text: 'white', shadow: '0 2px 4px rgba(184, 115, 51, 0.3)' },   // Cuivre
           { background: '#ffe5b4', border: '#ffc591', text: '#1f2937', shadow: '0 2px 4px rgba(255, 229, 180, 0.3)' }, // Pêche
           { background: '#e1ad01', border: '#c49100', text: 'white', shadow: '0 2px 4px rgba(225, 173, 1, 0.3)' },     // Moutarde
           { background: '#e2725b', border: '#c85a45', text: 'white', shadow: '0 2px 4px rgba(226, 114, 91, 0.3)' },    // Terracotta
       ];
   
       // VALIDATION: S'assurer que l'index est valide
       const validIndex = Math.max(0, Math.min(colorIndex, colors.length - 1));
   
       return colors[validIndex] || colors[0];
   }
   
   /* ================================
      DRAG & DROP SYSTEM
      ================================ */
   
   function initializeDragAndDrop() {
       // Vérifier si le planning est en mode brouillon
       const isDraft = window.IS_PLANNING_DRAFT !== undefined ? window.IS_PLANNING_DRAFT : true;
   
       if (!isDraft) {
           // Désactiver visuellement le drag & drop
           const codes = document.querySelectorAll('.assignment-code');
           codes.forEach(code => {
               code.draggable = false;
               code.style.cursor = 'default';
               code.style.opacity = '1';
           });
           return;
       }
   
       const cells = document.querySelectorAll('.assignment-cell');
   
       cells.forEach(cell => {
           // Vérifier si les listeners existent déjà pour éviter les duplications
           if (!dragAndDropListeners.has(cell)) {
               // Permettre le drop
               const dragOverHandler = (e) => handleDragOver(e);
               const dragEnterHandler = (e) => handleDragEnter(e);
               const dragLeaveHandler = (e) => handleDragLeave(e);
               const dropHandler = (e) => handleDrop(e);
   
               cell.addEventListener('dragover', dragOverHandler);
               cell.addEventListener('dragenter', dragEnterHandler);
               cell.addEventListener('dragleave', dragLeaveHandler);
               cell.addEventListener('drop', dropHandler);
   
               // Stocker les handlers pour pouvoir les retirer plus tard si nécessaire
               dragAndDropListeners.set(cell, {
                   dragover: dragOverHandler,
                   dragenter: dragEnterHandler,
                   dragleave: dragLeaveHandler,
                   drop: dropHandler
               });
           }
   
           // Rendre les codes draggables
           const code = cell.querySelector('.assignment-code');
           if (code && !code.hasAttribute('data-drag-initialized')) {
               code.draggable = true;
               code.style.cursor = 'grab';
               
               const dragStartHandler = (e) => handleDragStart(e);
               const dragEndHandler = (e) => handleDragEnd(e);
               
               code.addEventListener('dragstart', dragStartHandler);
               code.addEventListener('dragend', dragEndHandler);
               
               // Marquer comme initialisé pour éviter les duplications
               code.setAttribute('data-drag-initialized', 'true');
           }
       });
   }
   
   function handleDragStart(e) {
       // Vérifier si le planning est en mode brouillon
       const isDraft = window.IS_PLANNING_DRAFT !== undefined ? window.IS_PLANNING_DRAFT : true;
   
       if (!isDraft) {
           e.preventDefault();
           return;
       }
   
       dragSource = {
           element: e.target,
           cell: e.target.closest('.assignment-cell'),
           employeeCode: e.target.textContent.trim(),
           employeeId: e.target.getAttribute('data-employee-id'),
           assignmentId: e.target.getAttribute('data-assignment-id'),
           isSpecial: e.target.getAttribute('data-is-special') === 'true',
           color: e.target.getAttribute('data-color')
       };
   
       // Fermer le menu contextuel si ouvert
       if (typeof closeContextMenu === 'function') {
           closeContextMenu();
       }
   
       // Effet visuel sur l'élément qu'on traîne
       e.target.style.opacity = '0.5';
   
       // Marquer la cellule source
       dragSource.cell.classList.add('drag-source');
   
       // Marquer la ligne active
       const row = dragSource.cell.closest('tr');
       if (row) row.classList.add('drag-active');
   
       // Highlighting des zones de drop valides
       highlightValidDropZones();
   
       // Définir les données de transfer
       e.dataTransfer.effectAllowed = 'move';
       e.dataTransfer.setData('text/html', e.target.outerHTML);
   }
   
   function handleDragEnd(e) {
       // Nettoyer tous les états visuels
       cleanupDragVisuals();
       resetDrag();
   
       // Réinitialiser le menu contextuel après le drag
       setTimeout(() => {
           if (typeof initializeContextMenu === 'function') {
               initializeContextMenu();
           }
       }, 200);
   }
   
   function handleDragOver(e) {
       // Vérifier si le planning est en mode brouillon
       const isDraft = window.IS_PLANNING_DRAFT !== undefined ? window.IS_PLANNING_DRAFT : true;
   
       if (!isDraft) {
           e.preventDefault();
           e.dataTransfer.dropEffect = 'none';
           return;
       }
   
       e.preventDefault();
       e.dataTransfer.dropEffect = 'move';
   }
   
   function handleDragEnter(e) {
       // Vérifier si le planning est en mode brouillon
       const isDraft = window.IS_PLANNING_DRAFT !== undefined ? window.IS_PLANNING_DRAFT : true;
   
       if (!isDraft) {
           e.preventDefault();
           return;
       }
   
       e.preventDefault();
   
       if (!dragSource) return;
   
       const targetCell = e.currentTarget;
   
       // Ne pas highlight la cellule source
       if (targetCell === dragSource.cell) return;
   
       // Ajouter l'effet de survol
       targetCell.classList.add('drag-over');
   
       // Animation subtile
       targetCell.style.transform = 'scale(1.02)';
   }
   
   function handleDragLeave(e) {
       const targetCell = e.currentTarget;
   
       // Vérifier que la souris quitte vraiment la cellule
       const rect = targetCell.getBoundingClientRect();
       const x = e.clientX;
       const y = e.clientY;
   
       if (x < rect.left || x > rect.right || y < rect.top || y > rect.bottom) {
           targetCell.classList.remove('drag-over');
           targetCell.style.transform = '';
       }
   }
   
   function handleDrop(e) {
       e.preventDefault();
   
       // Vérifier si le planning est en mode brouillon
       const isDraft = window.IS_PLANNING_DRAFT !== undefined ? window.IS_PLANNING_DRAFT : true;
   
       if (!isDraft) {
           cleanupDragVisuals();
           resetDrag();
           return;
       }
   
       const targetCell = e.currentTarget;
   
       if (!dragSource) {
           return;
       }
   
       // Nettoyer l'état visuel
       targetCell.classList.remove('drag-over');
       targetCell.style.transform = '';
   
       // Ne pas permettre le drop sur la même cellule
       if (targetCell === dragSource.cell) {
           cleanupDragVisuals();
           resetDrag();
           return;
       }
   
       const targetCode = targetCell.querySelector('.assignment-code');
   
       if (targetCode) {
           // Échanger deux employés
           swapEmployees(dragSource, {
               element: targetCode,
               cell: targetCell,
               employeeCode: targetCode.textContent.trim(),
               employeeId: targetCode.getAttribute('data-employee-id'),
               assignmentId: targetCode.getAttribute('data-assignment-id'),
               isSpecial: targetCode.getAttribute('data-is-special') === 'true',
               color: targetCode.getAttribute('data-color')
           });
       } else {
           // Déplacer vers cellule vide
           moveEmployee(dragSource, targetCell);
       }
   
       cleanupDragVisuals();
       resetDrag();
   }
   
   function highlightValidDropZones() {
       const allCells = document.querySelectorAll('.assignment-cell');
       allCells.forEach(cell => {
           if (cell !== dragSource.cell) {
               cell.classList.add('valid-drop-zone');
           }
       });
   
       setTimeout(() => {
           allCells.forEach(cell => cell.classList.remove('valid-drop-zone'));
       }, 2000);
   }
   
   function cleanupDragVisuals() {
       document.querySelectorAll('.drag-source').forEach(el =>
           el.classList.remove('drag-source'));
       document.querySelectorAll('.drag-over').forEach(el =>
           el.classList.remove('drag-over'));
       document.querySelectorAll('.drag-active').forEach(el =>
           el.classList.remove('drag-active'));
       document.querySelectorAll('.valid-drop-zone').forEach(el =>
           el.classList.remove('valid-drop-zone'));
   
       document.querySelectorAll('.assignment-cell').forEach(cell => {
           cell.style.transform = '';
       });
   }
   
   function resetDrag() {
       if (dragSource) {
           dragSource.element.style.opacity = '1';
           dragSource = null;
       }
   }
   
   /* ================================
      OPÉRATIONS DRAG & DROP
      ================================ */
   
   function swapEmployees(source, target) {
       // Validation avant modification
       if (!source || !target || !source.cell || !target.cell) {
           showDragNotification('Erreur: Données invalides', 'error');
           cleanupDragVisuals();
           resetDrag();
           return;
       }
   
       // Valider que les assignment_id existent
       if (!source.assignmentId || !target.assignmentId) {
           showDragNotification('Erreur: Affectations invalides', 'error');
           cleanupDragVisuals();
           resetDrag();
           return;
       }
   
       const sourceData = getCellDataSimple(source.cell, source);
       const targetData = getCellDataSimple(target.cell, target);
   
       // Sauvegarder l'état actuel pour rollback
       const stateBefore = {
           source: {
               element: source.element,
               textContent: source.element.textContent,
               employeeId: source.element.getAttribute('data-employee-id'),
               assignmentId: source.element.getAttribute('data-assignment-id'),
               color: source.element.getAttribute('data-color')
           },
           target: {
               element: target.element,
               textContent: target.element.textContent,
               employeeId: target.element.getAttribute('data-employee-id'),
               assignmentId: target.element.getAttribute('data-assignment-id'),
               color: target.element.getAttribute('data-color')
           }
       };
   
       showDragNotification('Échange en cours...', 'info');
   
       animateSwap(source.element, target.element, () => {
           // Modifier le DOM
           // IMPORTANT: On échange seulement les employés affichés, PAS les IDs d'affectation
           // car le serveur échange les employés dans les affectations, pas les affectations elles-mêmes
           const tempCode = source.employeeCode;
           const tempId = source.employeeId;
           const tempColor = source.color;
   
           // Échanger les employés affichés
           source.element.textContent = target.employeeCode;
           source.element.setAttribute('data-employee-id', target.employeeId);
           source.element.setAttribute('data-color', target.color);
           // NE PAS échanger les assignment-id car ils restent liés à leur position
   
           target.element.textContent = tempCode;
           target.element.setAttribute('data-employee-id', tempId);
           target.element.setAttribute('data-color', tempColor);
           // NE PAS échanger les assignment-id car ils restent liés à leur position
   
           applyEmployeeColors();
           
           // Réinitialiser le drag & drop sans recréer tous les listeners
           reinitializeDragAndDropForCells([source.cell, target.cell]);
   
           // Réinitialiser le menu contextuel
           setTimeout(() => {
               if (typeof initializeContextMenu === 'function') {
                   initializeContextMenu();
               }
           }, 200);
   
           // Sauvegarder avec gestion d'erreur et rollback
           saveToServerWithRollback('swap', sourceData, targetData, stateBefore, () => {
               // Rollback en cas d'erreur
               rollbackSwap(stateBefore);
           });
       });
   }
   
   function moveEmployee(source, targetCell) {
       // Validation avant modification
       if (!source || !source.cell || !targetCell) {
           showDragNotification('Erreur: Données invalides', 'error');
           cleanupDragVisuals();
           resetDrag();
           return;
       }
   
       if (!source.assignmentId) {
           showDragNotification('Erreur: Affectation source invalide', 'error');
           cleanupDragVisuals();
           resetDrag();
           return;
       }
   
       // Vérifier que la cellule cible est vide
       const existingCode = targetCell.querySelector('.assignment-code');
       if (existingCode) {
           showDragNotification('Erreur: La cellule cible n\'est pas vide', 'error');
           cleanupDragVisuals();
           resetDrag();
           return;
       }
   
       const sourceData = getCellDataSimple(source.cell, source);
       const targetData = getCellDataSimple(targetCell, null);
   
       // Sauvegarder l'état actuel pour rollback
       const sourceWrapper = source.element.closest('.assignment-wrapper');
       const stateBefore = {
           sourceWrapper: sourceWrapper ? sourceWrapper.cloneNode(true) : null,
           sourceCell: source.cell,
           targetCell: targetCell,
           sourceElement: source.element
       };
   
       showDragNotification('Déplacement en cours...', 'info');
   
       animateMove(source.element, targetCell, () => {
           // Modifier le DOM
           const wrapper = document.createElement('div');
           wrapper.className = 'assignment-wrapper';
   
           const newCode = document.createElement('div');
           newCode.className = 'assignment-code';
           newCode.textContent = source.employeeCode;
           newCode.setAttribute('data-employee-id', source.employeeId);
           newCode.setAttribute('data-assignment-id', source.assignmentId);
           newCode.setAttribute('data-color', source.color);
   
           wrapper.appendChild(newCode);
           targetCell.appendChild(wrapper);
   
           if (sourceWrapper) {
               sourceWrapper.remove();
           }
   
           applyEmployeeColors();
           
           // Réinitialiser le drag & drop sans recréer tous les listeners
           reinitializeDragAndDropForCells([source.cell, targetCell]);
   
           // Réinitialiser le menu contextuel
           setTimeout(() => {
               if (typeof initializeContextMenu === 'function') {
                   initializeContextMenu();
               }
           }, 200);
   
           // Sauvegarder avec gestion d'erreur et rollback
           saveToServerWithRollback('move', sourceData, targetData, stateBefore, () => {
               // Rollback en cas d'erreur
               rollbackMove(stateBefore);
           });
       });
   }
   
   function animateSwap(element1, element2, callback) {
       // Animation simple avec un flash visuel au lieu des mouvements complexes
   
       // Phase 1: Flash de highlight sur les deux éléments
       element1.style.transition = 'all 0.15s ease';
       element2.style.transition = 'all 0.15s ease';
   
       // Highlight simultané des deux éléments
       element1.style.backgroundColor = '#fef3c7'; // Jaune clair
       element2.style.backgroundColor = '#fef3c7';
       element1.style.transform = 'scale(1.05)';
       element2.style.transform = 'scale(1.05)';
       element1.style.boxShadow = '0 4px 12px rgba(251, 191, 36, 0.4)';
       element2.style.boxShadow = '0 4px 12px rgba(251, 191, 36, 0.4)';
   
       setTimeout(() => {
           // Phase 2: Retour à l'état normal avec un petit "pulse"
           element1.style.transform = 'scale(0.95)';
           element2.style.transform = 'scale(0.95)';
   
           setTimeout(() => {
               // Phase 3: Reset complet et callback
               element1.style.transition = '';
               element2.style.transition = '';
               element1.style.transform = '';
               element2.style.transform = '';
               element1.style.backgroundColor = '';
               element2.style.backgroundColor = '';
               element1.style.boxShadow = '';
               element2.style.boxShadow = '';
   
               callback();
           }, 100);
       }, 150);
   }
   
   function animateMove(element, targetCell, callback) {
       const rect1 = element.getBoundingClientRect();
       const rect2 = targetCell.getBoundingClientRect();
   
       const deltaX = rect2.left - rect1.left;
       const deltaY = rect2.top - rect1.top;
   
       element.style.transition = 'transform 0.4s cubic-bezier(0.25, 0.46, 0.45, 0.94)';
       element.style.transform = `translate(${deltaX}px, ${deltaY}px) scale(1.1) rotate(10deg)`;
       element.style.zIndex = '1000';
   
       setTimeout(() => {
           callback();
       }, 400);
   }
   
   function showDragNotification(message, type) {
       document.querySelectorAll('.drag-notification').forEach(n => n.remove());
   
       const notification = document.createElement('div');
       notification.className = `drag-notification ${type}`;
       notification.innerHTML = `
           ${message}
           <button type="button" style="margin-left: 10px; background: none; border: none; font-size: 16px; cursor: pointer;" onclick="this.parentNode.remove()">×</button>
       `;
   
       document.body.appendChild(notification);
   
       setTimeout(() => {
           if (notification.parentNode) {
               notification.remove();
           }
       }, 3000);
   }
   
   /* ================================
      MENU CONTEXTUEL - INITIALISATION
      ================================ */
   
   function initializeContextMenu() {
       // Vérifier si le planning est en mode brouillon
       const isDraft = window.IS_PLANNING_DRAFT !== undefined ? window.IS_PLANNING_DRAFT : true;
   
       if (!isDraft) {
           return;
       }
   
       // Créer le menu contextuel
       createContextMenu();
   
       // Ajouter les événements click droit
       const cells = document.querySelectorAll('.assignment-cell');
       cells.forEach(cell => {
           // Supprimer l'ancien event listener s'il existe
           cell.removeEventListener('contextmenu', handleContextMenu);
           // Ajouter le nouvel event listener
           cell.addEventListener('contextmenu', handleContextMenu);
       });
   
       // Fermer le menu en cliquant ailleurs
       document.removeEventListener('click', closeContextMenu);
       document.removeEventListener('scroll', closeContextMenu);
       document.addEventListener('click', closeContextMenu);
       document.addEventListener('scroll', closeContextMenu);
   }
   
   /* ================================
      CRÉATION DU MENU - MODIFIÉE POUR ÉVITER LE SCROLL
      ================================ */
   
   function createContextMenu() {
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
           width: 320px;
           height: auto;
           display: none;
           font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
           overflow: hidden;
           box-sizing: border-box;
           animation: contextMenuFadeIn 0.2s ease-out;
       `;
   
       contextMenu.innerHTML = `
           <div class="context-menu-header-chc" style="
               background: #1e3a8a;
               color: white;
               padding: 12px 16px;
               font-weight: 600;
               font-size: 0.85rem;
               letter-spacing: 0.025em;
               border-bottom: 1px solid #e5e7eb;
           ">
               <span class="context-menu-title-chc">Actions disponibles</span>
           </div>
           <div class="context-menu-content-chc" style="
               height: auto;
               overflow: hidden;
               padding: 6px 0 12px 0;
               display: flex;
               flex-direction: column;
               box-sizing: border-box;
           ">
               <div class="context-menu-loading-chc" style="
                   padding: 16px;
                   text-align: center;
                   color: #6b7280;
                   font-style: italic;
                   font-size: 0.85rem;
               ">
                   <i class="fa fa-spinner fa-spin" style="margin-right: 8px; color: #1e3a8a;"></i> 
                   Chargement...
               </div>
           </div>
       `;
   
       document.body.appendChild(contextMenu);
   }
   
   function handleContextMenu(e) {
       // Vérifier si le planning est en mode brouillon
       const isDraft = window.IS_PLANNING_DRAFT !== undefined ? window.IS_PLANNING_DRAFT : true;
   
       if (!isDraft) {
           e.preventDefault();
           return false;
       }
   
       e.preventDefault();
       e.stopPropagation();
   
       const cell = e.currentTarget;
       const assignmentCode = cell.querySelector('.assignment-code');
   
       contextMenuTarget = {
           cell: cell,
           assignmentCode: assignmentCode,
           isEmpty: !assignmentCode,
           position: getCellPosition(cell)
       };
   
       showContextMenu(e.pageX, e.pageY);
   
       if (contextMenuTarget.isEmpty) {
           loadAvailableEmployees();
       } else {
           loadReplacementSuggestions();
       }
   
       return false;
   }
   
   function showContextMenu(x, y) {
       if (!contextMenu) return;
   
       // Positionner temporairement le menu hors écran pour mesurer sa taille
       contextMenu.style.display = 'block';
       contextMenu.style.visibility = 'hidden';
       contextMenu.style.left = '-9999px';
       contextMenu.style.top = '-9999px';
   
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
   
   // Recalage après chargement du contenu (quand la hauteur réelle est connue)
   function adjustContextMenuAfterContent() {
       if (!contextMenu || contextMenu.style.display === 'none') {
           return;
       }
   
       const rect = contextMenu.getBoundingClientRect();
       const windowWidth = window.innerWidth;
       const windowHeight = window.innerHeight;
   
       let finalLeft = rect.left;
       let finalTop = rect.top;
   
       // Si on déborde à droite, on recale vers la gauche
       if (rect.right > windowWidth) {
           finalLeft = Math.max(10, windowWidth - rect.width - 10);
       }
   
       // Si on déborde en bas, on remonte le menu
       if (rect.bottom > windowHeight) {
           finalTop = Math.max(10, windowHeight - rect.height - 10);
       }
   
       contextMenu.style.left = finalLeft + 'px';
       contextMenu.style.top = finalTop + 'px';
   }
   
   function closeContextMenu() {
       if (contextMenu) {
           contextMenu.style.display = 'none';
       }
       contextMenuTarget = null;
   }
   
   /* ================================
      MENU CONTEXTUEL - ANALYSE DE POSITION
      ================================ */
   
   function getCellPosition(cell) {
       const row = cell.closest('tr');
       const cellIndex = Array.from(row.cells).indexOf(cell);
   
       // Déterminer si c'est une cellule journée complète
       const isFullDay = cell.hasAttribute('colspan') && cell.getAttribute('colspan') === '2';
   
       let dayColumnIndex, period;
   
       if (isFullDay) {
           // Pour les cellules full-day (MLE On Site), vérifier si la première cellule de la ligne
           // est la cellule site (elle n'existe que sur la première ligne à cause du rowspan)
           const firstCell = row.cells[0];
           const hasSiteCell = firstCell && firstCell.classList.contains('site-cell');
   
           if (hasSiteCell) {
               // La cellule site existe dans cette ligne → soustraire 1
               dayColumnIndex = cellIndex - 1;
           } else {
               // La cellule site n'existe pas dans cette ligne (rowspan) → utiliser directement l'index
               dayColumnIndex = cellIndex;
           }
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
   
       // Détecter si c'est une perm spéciale
       const table = cell.closest('table');
       const isSpecialTable = table && table.classList.contains('special-table');
       const isSpecialRow = row && row.classList.contains('special-row');
       const isSpecial = isSpecialTable || isSpecialRow;
   
       if (isSpecial) {
           // Pour les perms spéciales, utiliser TCH (technique) comme qualification
           permanenceType = 'TCH';
           if (siteCell) {
               const siteFullname = siteCell.querySelector('.site-fullname');
               if (siteFullname) {
                   // Le nom de la permanence spéciale (ex: "Accréditation", "Formation", ...)
                   siteName = siteFullname.textContent.trim();
               }
           }
       } else if (siteCell) {
           const siteFullname = siteCell.querySelector('.site-fullname');
   
           if (siteFullname) {
               siteName = siteFullname.textContent.trim();
   
               // Extraire le code du site depuis le texte
               // Format 1: "Nom (CODE)" - ex: "Mont Légia (MLE)"
               let match = siteName.match(/\(([A-Z]+)\)/);
               if (match) {
                   siteCode = match[1];
               } else {
                   // Format 2: "On Site XXX" - ex: "On Site HRM", "On Site HEU", "On Site WAR"
                   match = siteName.match(/On Site\s+([A-Z]{3})/i);
                   if (match) {
                       siteCode = match[1].toUpperCase();
                   } else {
                       // Format 3: Vérifier si le nom contient directement HRM, HEU, WAR
                       const upperName = siteName.toUpperCase();
                       if (upperName.includes('HRM')) {
                           siteCode = 'HRM';
                       } else if (upperName.includes('HEU')) {
                           siteCode = 'HEU';
                       } else if (upperName.includes('WAR')) {
                           siteCode = 'WAR';
                       } else if (upperName.includes('MLE') || upperName.includes('MONT LÉGIA') || upperName.includes('MONT LEGIA')) {
                           siteCode = 'MLE';
                       }
                   }
               }
   
               // Déterminer le type de permanence selon le nom et le code
               const lowerName = siteName.toLowerCase();
               if (siteCode === 'HRM' || siteCode === 'HEU' || siteCode === 'WAR') {
                   // Pour les sites HRM, HEU, WAR, toujours utiliser TCH
                   permanenceType = 'TCH';
               } else if (lowerName.includes('on site mle') || lowerName.includes('atelier')) {
                   permanenceType = 'ATL';
               } else if (lowerName.includes('fonctionnelle')) {
                   permanenceType = 'FCT';
               } else if (lowerName.includes('technique')) {
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
           permanence_type: permanenceType,
           is_special: isSpecial || false
       };
   }
   
   /* ================================
      CHARGEMENT DES SUGGESTIONS
      ================================ */
   
   function loadAvailableEmployees() {
       if (!contextMenuTarget) return;
   
       const position = contextMenuTarget.position;
       const planningId = getPlanningId();
   
       if (!planningId) {
           showContextMenuError('Erreur: Planning non trouvé');
           return;
       }
   
       const data = {
           planning_id: planningId,
           position: position,
           action: 'get_available_employees'
       };
   
       fetchEmployeeSuggestions(data, 'Employés disponibles', 'assign');
   }
   
   function loadReplacementSuggestions() {
       if (!contextMenuTarget || !contextMenuTarget.assignmentCode) return;
   
       const assignmentId = contextMenuTarget.assignmentCode.getAttribute('data-assignment-id');
       const position = contextMenuTarget.position;
       const planningId = getPlanningId();
   
       if (!planningId || !assignmentId) {
           showContextMenuError('Erreur: Données manquantes');
           return;
       }
   
       // Ajouter is_special à la position si c'est une perm spéciale
       const isSpecial = contextMenuTarget.assignmentCode.getAttribute('data-is-special') === 'true';
       if (isSpecial) {
           position.is_special = true;
       }
   
       const data = {
           planning_id: planningId,
           assignment_id: parseInt(assignmentId),
           position: position,
           action: 'get_replacement_suggestions'
       };
   
       fetchEmployeeSuggestions(data, 'Suggestions de remplacement', 'replace');
   }
   
   function fetchEmployeeSuggestions(data, title, actionType) {
       const payload = {
           jsonrpc: "2.0",
           method: "call",
           params: data,
           id: Math.floor(Math.random() * 1000000)
       };
   
       fetch('/planning/get_employee_suggestions', {
           method: 'POST',
           headers: {
               'Content-Type': 'application/json',
               'X-Requested-With': 'XMLHttpRequest'
           },
           body: JSON.stringify(payload)
       })
           .then(response => response.json())
           .then(result => {
               const actualResult = result.result || result;
   
               if (actualResult && actualResult.success) {
                   displayEmployeeSuggestions(actualResult.employees, title, actionType);
               } else {
                   showContextMenuError(actualResult.error || 'Erreur inconnue');
               }
           })
           .catch(error => {
               showContextMenuError('Erreur de connexion');
           });
   }
   
   /* ================================
      AFFICHAGE DES SUGGESTIONS - MODIFIÉ POUR 5 MAX
      ================================ */
   
   function displayEmployeeSuggestions(employees, title, actionType) {
       if (!contextMenu) return;
   
       const content = contextMenu.querySelector('.context-menu-content-chc');
       const header = contextMenu.querySelector('.context-menu-title-chc');
   
       header.textContent = title;
   
       let html = '';
   
       // Si c'est un remplacement (actionType === 'replace'), ajouter l'option "RETIRER" en premier
       if (actionType === 'replace' && contextMenuTarget && contextMenuTarget.assignmentCode) {
           const assignmentId = contextMenuTarget.assignmentCode.getAttribute('data-assignment-id');
           html += `
               <div class="context-menu-item-chc remove" 
                    data-assignment-id="${assignmentId}"
                    onclick="removeAssignment(this)"
                    style="
                        display: flex;
                        align-items: center;
                        padding: 10px 16px;
                        cursor: pointer;
                        color: #dc2626;
                        border-bottom: 1px solid #e5e7eb;
                        font-weight: 500;
                        transition: all 0.25s ease;
                        min-height: 40px;
                    "
                    onmouseover="this.style.backgroundColor='#fee2e2'; this.style.borderLeft='3px solid #dc2626'; this.style.paddingLeft='13px';"
                    onmouseout="this.style.backgroundColor=''; this.style.borderLeft=''; this.style.paddingLeft='16px';">
                   <i class="fa fa-trash" style="margin-right: 10px; width: 16px; text-align: center; font-size: 0.8rem;"></i> 
                   RETIRER l'assignation
               </div>
               <div class="context-menu-separator-chc" style="
                   height: 1px;
                   background: #e5e7eb;
                   margin: 4px 0 2px 0;
                   flex-shrink: 0;
               "></div>
           `;
       }
   
       if (!employees || employees.length === 0) {
           html += `
               <div class="context-menu-item-chc disabled" style="
                   display: flex;
                   align-items: center;
                   padding: 12px 18px;
                   color: #9ca3af;
                   cursor: not-allowed;
                   font-style: italic;
               ">
                   <i class="fa fa-exclamation-triangle" style="margin-right: 10px;"></i>
                   Aucun employé disponible
               </div>
           `;
           content.innerHTML = html;
           return;
       }
   
       // ✅ AFFICHAGE DE TOUS LES EMPLOYÉS AVEC SCROLL INTERNE DANS LE MENU
       // (la hauteur est limitée côté CSS, le contenu est scrollable)
   
       employees.forEach((emp, index) => {
           const qualificationText = getQualificationText(emp.qualification_priority);
           const colorStyle = getEmployeeColorStyle(emp.color);
           const workloadText = emp.workload_info?.text || 'Disponible';
   
           html += `
               <div class="context-menu-item-chc" 
                    data-employee-id="${emp.id}" 
                    data-action="${actionType}"
                    data-qualification="${emp.qualification_priority}"
                    onclick="handleEmployeeSelection(this)"
                    style="
                        display: flex;
                        align-items: center;
                        padding: 10px 16px;
                        cursor: pointer;
                        transition: all 0.25s ease;
                        border: none;
                        background: none;
                        width: 100%;
                        text-align: left;
                        font-size: 0.8rem;
                        position: relative;
                        overflow: hidden;
                        box-sizing: border-box;
                        min-height: 44px;
                    "
                    onmouseover="this.style.backgroundColor='#f9fafb'; this.style.borderLeft='3px solid #1e3a8a'; this.style.paddingLeft='13px';"
                    onmouseout="this.style.backgroundColor=''; this.style.borderLeft=''; this.style.paddingLeft='16px';">
                   <div class="employee-suggestion-chc" style="
                       display: flex;
                       align-items: center;
                       gap: 12px;
                       width: 100%;
                   ">
                       <div class="employee-code-chc" style="
                           display: flex;
                           align-items: center;
                           justify-content: center;
                           width: 48px;
                           height: 32px;
                           border-radius: 6px;
                           font-weight: 700;
                           font-size: 0.75rem;
                           border: 2px solid;
                           flex-shrink: 0;
                           box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
                           transition: all 0.2s ease;
                           ${colorStyle}
                       ">
                           ${emp.code}
                       </div>
                       <div class="employee-details-chc" style="
                           flex: 1;
                           min-width: 0;
                       ">
                           <div class="employee-name-chc" style="
                               font-weight: 600;
                               color: #1e3a8a;
                               margin-bottom: 2px;
                               font-size: 0.85rem;
                               white-space: nowrap;
                               overflow: hidden;
                               text-overflow: ellipsis;
                               transition: color 0.2s ease;
                           ">${emp.name}</div>
                           <div class="employee-qualification-chc" style="
                               font-size: 0.72rem;
                               color: #6b7280;
                               line-height: 1.3;
                               display: flex;
                               align-items: center;
                               gap: 4px;
                               transition: color 0.2s ease;
                           ">
                               ${workloadText}
                           </div>
                       </div>
                   </div>
               </div>
           `;
       });
   
       // Ajouter option d'annulation
       html += `
           <div class="context-menu-separator-chc" style="
               height: 1px;
               background: #e5e7eb;
               margin: 4px 0 2px 0;
               flex-shrink: 0;
           "></div>
           <div class="context-menu-item-chc cancel" 
                onclick="closeContextMenu()"
                style="
                    display: flex;
                    align-items: center;
                    padding: 10px 16px;
                    cursor: pointer;
                    color: #6b7280;
                    border-top: 1px solid #e5e7eb;
                    font-weight: 500;
                    margin-top: 2px;
                    margin-bottom: 0;
                    transition: all 0.25s ease;
                    min-height: 40px;
                    box-sizing: border-box;
                "
                onmouseover="this.style.backgroundColor='#fee2e2'; this.style.borderLeft='3px solid #e53e3e'; this.style.color='#e53e3e';"
                onmouseout="this.style.backgroundColor=''; this.style.borderLeft=''; this.style.color='#6b7280';">
               <i class="fa fa-times" style="margin-right: 8px; width: 16px; text-align: center; font-size: 0.8rem;"></i> 
               Annuler
           </div>
       `;
   
       content.innerHTML = html;
   
       // Recalage de la position une fois les suggestions insérées
       adjustContextMenuAfterContent();
   }
   
   function getQualificationText(priority) {
       const qualifications = {
           '1': 'Expert',
           '2': 'Avancé',
           '3': 'Intermédiaire',
           '4': 'Débutant',
           '5': 'Occasion'
       };
       return qualifications[priority] || 'Non défini';
   }
   
   function getEmployeeColorStyle(colorIndex) {
       // Utiliser la fonction existante du planning principal
       if (typeof getEmployeeColors === 'function') {
           const colors = getEmployeeColors(colorIndex);
           return `background-color: ${colors.background}; color: ${colors.text}; border-color: ${colors.border};`;
       }
   
       // Fallback si la fonction n'est pas disponible
       return `background-color: #fbbf24; color: #1f2937; border-color: #f59e0b;`;
   }
   
   function showContextMenuError(message) {
       if (!contextMenu) return;
   
       const content = contextMenu.querySelector('.context-menu-content-chc');
       const header = contextMenu.querySelector('.context-menu-title-chc');
   
       header.textContent = 'Erreur';
       content.innerHTML = `
           <div class="context-menu-item-chc error" style="
               display: flex;
               align-items: center;
               padding: 12px 18px;
               color: #e53e3e;
               cursor: default;
           ">
               <i class="fa fa-exclamation-circle" style="margin-right: 10px; width: 18px; text-align: center; color: #e53e3e;"></i>
               ${message}
           </div>
           <div class="context-menu-separator-chc" style="
               height: 1px;
               background: #e5e7eb;
               margin: 8px 0 2px 0;
               flex-shrink: 0;
           "></div>
           <div class="context-menu-item-chc cancel" 
                onclick="closeContextMenu()"
                style="
                    display: flex;
                    align-items: center;
                    padding: 12px 18px;
                    cursor: pointer;
                    color: #6b7280;
                    font-weight: 500;
                    margin-bottom: 0;
                    transition: all 0.25s ease;
                    box-sizing: border-box;
                "
                onmouseover="this.style.backgroundColor='#fee2e2'; this.style.color='#e53e3e';"
                onmouseout="this.style.backgroundColor=''; this.style.color='#6b7280';">
               <i class="fa fa-times" style="margin-right: 10px; width: 18px; text-align: center;"></i> 
               Fermer
           </div>
       `;
   }
   
   /* ================================
      ACTIONS D'AFFECTATION
      ================================ */
   
   function handleEmployeeSelection(element) {
       const employeeId = element.getAttribute('data-employee-id');
       const action = element.getAttribute('data-action');
   
       if (!contextMenuTarget || !employeeId) {
           closeContextMenu();
           return;
       }
   
       if (action === 'assign') {
           assignEmployeeToCell(employeeId);
       } else if (action === 'replace') {
           replaceEmployeeInCell(employeeId);
       }
   
       closeContextMenu();
   }
   
   function removeAssignment(element) {
       const assignmentId = element.getAttribute('data-assignment-id');
       const planningId = getPlanningId();
   
       if (!planningId || !assignmentId) {
           showContextNotification('Erreur: Données manquantes', 'error');
           closeContextMenu();
           return;
       }
   
       // Ajouter is_special à la position si c'est une perm spéciale
       const isSpecial = contextMenuTarget && contextMenuTarget.assignmentCode &&
           contextMenuTarget.assignmentCode.getAttribute('data-is-special') === 'true';
       const position = contextMenuTarget ? (contextMenuTarget.position || {}) : {};
       if (isSpecial) {
           position.is_special = true;
       }
   
       const data = {
           planning_id: planningId,
           assignment_id: parseInt(assignmentId),
           position: position,
           action: 'remove_assignment'
       };
   
       executeAssignmentAction(data, 'Suppression en cours...');
       closeContextMenu();
   }
   
   function assignEmployeeToCell(employeeId) {
       const planningId = getPlanningId();
       if (!planningId) {
           showContextNotification('Erreur: Planning non trouvé', 'error');
           return;
       }
   
       const data = {
           planning_id: planningId,
           employee_id: parseInt(employeeId),
           position: contextMenuTarget.position,
           action: 'assign_employee'
       };
   
       executeAssignmentAction(data, 'Affectation en cours...');
   }
   
   function replaceEmployeeInCell(employeeId) {
       const assignmentId = contextMenuTarget.assignmentCode.getAttribute('data-assignment-id');
       const planningId = getPlanningId();
   
       if (!planningId || !assignmentId) {
           showContextNotification('Erreur: Données manquantes', 'error');
           return;
       }
   
       // Ajouter is_special à la position si c'est une perm spéciale
       const isSpecial = contextMenuTarget.assignmentCode.getAttribute('data-is-special') === 'true';
       const position = contextMenuTarget.position || {};
       if (isSpecial) {
           position.is_special = true;
       }
   
       const data = {
           planning_id: planningId,
           assignment_id: parseInt(assignmentId),
           new_employee_id: parseInt(employeeId),
           position: position,
           action: 'replace_employee'
       };
   
       executeAssignmentAction(data, 'Remplacement en cours...');
   }
   
   function executeAssignmentAction(data, loadingMessage) {
       showContextNotification(loadingMessage, 'info');
   
       const payload = {
           jsonrpc: "2.0",
           method: "call",
           params: data,
           id: Math.floor(Math.random() * 1000000)
       };
   
       fetch('/planning/context_menu_action', {
           method: 'POST',
           headers: {
               'Content-Type': 'application/json',
               'X-Requested-With': 'XMLHttpRequest'
           },
           body: JSON.stringify(payload)
       })
           .then(response => response.json())
           .then(result => {
               const actualResult = result.result || result;
   
               if (actualResult && actualResult.success) {
                   showContextNotification(actualResult.message, 'success');
   
                   // Recharger la page pour voir les changements
                   setTimeout(() => {
                       location.reload();
                   }, 1500);
               } else {
                   showContextNotification(actualResult.error || 'Erreur inconnue', 'error');
               }
           })
           .catch(error => {
               showContextNotification('Erreur de connexion', 'error');
           });
   }
   
   function showContextNotification(message, type) {
       // Supprimer notifications existantes du menu contextuel
       document.querySelectorAll('.context-notification').forEach(n => n.remove());
   
       const notification = document.createElement('div');
       notification.className = `alert alert-${type} context-notification`;
       notification.style.cssText = `
           position: fixed;
           top: 20px;
           right: 20px;
           z-index: 10050;
           padding: 12px 20px;
           border-radius: 6px;
           box-shadow: 0 4px 12px rgba(0,0,0,0.15);
           min-width: 300px;
           max-width: 400px;
           border-left: 4px solid ${type === 'success' ? '#059669' : type === 'error' ? '#e53e3e' : '#0ea5e9'};
           background: ${type === 'success' ? 'rgba(240, 253, 244, 0.95)' : type === 'error' ? 'rgba(254, 242, 242, 0.95)' : 'rgba(240, 249, 255, 0.95)'};
       `;
       notification.innerHTML = `
           ${message}
           <button type="button" style="margin-left: 10px; background: none; border: none; font-size: 16px; cursor: pointer;" onclick="this.parentNode.remove()">×</button>
       `;
   
       document.body.appendChild(notification);
   
       setTimeout(() => {
           if (notification.parentNode) {
               notification.remove();
           }
       }, 4000);
   }
   
   /* ================================
      EXTRACTION DES DONNÉES ET UTILITAIRES
      ================================ */
   
   function getCellDataSimple(cell, elementData) {
       // Validation de base
       if (!cell) {
           console.warn('getCellDataSimple: cell est null ou undefined');
           return {
               employee_code: null,
               employee_id: null,
               assignment_id: null,
               is_special: false,
               day_index: 0,
               period: 'am',
               site_code: 'MLE',
               site_name: 'Mont Légia'
           };
       }
   
       try {
           // Extraire les vraies données de la position de la cellule
           const row = cell.closest('tr');
           const table = cell.closest('table');
   
           if (!row) {
               console.warn('getCellDataSimple: impossible de trouver la ligne parente');
               return {
                   employee_code: elementData ? elementData.employeeCode : null,
                   employee_id: elementData ? elementData.employeeId : null,
                   assignment_id: elementData ? elementData.assignmentId : null,
                   is_special: false,
                   day_index: 0,
                   period: 'am',
                   site_code: 'MLE',
                   site_name: 'Mont Légia'
               };
           }
   
           // Trouver l'index de la colonne pour déterminer le jour et la période
           const cellIndex = Array.from(row.cells).indexOf(cell);
   
           if (cellIndex === -1) {
               console.warn('getCellDataSimple: impossible de trouver l\'index de la cellule');
               return {
                   employee_code: elementData ? elementData.employeeCode : null,
                   employee_id: elementData ? elementData.employeeId : null,
                   assignment_id: elementData ? elementData.assignmentId : null,
                   is_special: false,
                   day_index: 0,
                   period: 'am',
                   site_code: 'MLE',
                   site_name: 'Mont Légia'
               };
           }
   
           // Vérifier si c'est une cellule journée complète (colspan="2")
           const isFullDay = cell.hasAttribute('colspan') && cell.getAttribute('colspan') === '2';
   
           let dayColumnIndex, period;
   
           if (isFullDay) {
               // Pour les cellules full-day (MLE On Site), vérifier si la première cellule de la ligne
               // est la cellule site (elle n'existe que sur la première ligne à cause du rowspan)
               const firstCell = row.cells[0];
               const hasSiteCell = firstCell && firstCell.classList.contains('site-cell');
   
               if (hasSiteCell) {
                   // La cellule site existe dans cette ligne → soustraire 1
                   dayColumnIndex = cellIndex - 1;
               } else {
                   // La cellule site n'existe pas dans cette ligne (rowspan) → utiliser directement l'index
                   dayColumnIndex = cellIndex;
               }
               period = 'full';
           } else {
               // La première colonne (index 0) est pour le site/permanence
               // Les colonnes suivantes sont par paire : AM/PM pour chaque jour
               dayColumnIndex = Math.floor((cellIndex - 1) / 2);
               const isAM = (cellIndex - 1) % 2 === 0;
               period = isAM ? 'am' : 'pm';
           }
   
           // Déterminer le site et type de permanence depuis la première cellule de la ligne
           const siteCell = row.querySelector('.site-cell');
           let siteCode = 'MLE';
           let siteName = 'Mont Légia';
   
           if (siteCell) {
               const siteFullname = siteCell.querySelector('.site-fullname');
   
               if (siteFullname) {
                   siteName = siteFullname.textContent.trim();
                   
                   // Extraire le code du site depuis le texte
                   // Format 1: "Nom (CODE)" - ex: "Mont Légia (MLE)"
                   let match = siteName.match(/\(([A-Z]+)\)/);
                   if (match) {
                       siteCode = match[1];
                   } else {
                       // Format 2: "On Site XXX" - ex: "On Site HRM", "On Site HEU", "On Site WAR"
                       match = siteName.match(/On Site\s+([A-Z]{3})/i);
                       if (match) {
                           siteCode = match[1].toUpperCase();
                       } else {
                           // Format 3: Vérifier si le nom contient directement HRM, HEU, WAR
                           const upperName = siteName.toUpperCase();
                           if (upperName.includes('HRM')) {
                               siteCode = 'HRM';
                           } else if (upperName.includes('HEU')) {
                               siteCode = 'HEU';
                           } else if (upperName.includes('WAR')) {
                               siteCode = 'WAR';
                           } else if (upperName.includes('MLE') || upperName.includes('MONT LÉGIA') || upperName.includes('MONT LEGIA')) {
                               siteCode = 'MLE';
                           }
                       }
                   }
               }
           }
   
           // Détecter si c'est une perm spéciale
           // Les perms spéciales peuvent être :
           // - dans un tableau avec la classe "special-table"
           // - dans une ligne avec la classe "special-row"
           // - marquées directement sur l'élément avec data-is-special="true"
           const isSpecialTable = table && table.classList.contains('special-table');
           const isSpecialRow = row && row.classList.contains('special-row');
           const codeElement = cell.querySelector('.assignment-code');
           const isSpecialFromElement = codeElement && codeElement.getAttribute('data-is-special') === 'true';
           const isSpecial = isSpecialTable || isSpecialRow || isSpecialFromElement;
   
           const result = {
               employee_code: elementData ? elementData.employeeCode : null,
               employee_id: elementData ? elementData.employeeId : null,
               assignment_id: elementData ? elementData.assignmentId : null,
               is_special: isSpecial || false,
               day_index: Math.max(0, Math.min(4, dayColumnIndex)), // 0-4 pour lundi-vendredi
               period: period || 'am',
               site_code: siteCode || 'MLE',
               site_name: siteName || 'Mont Légia'
           };
   
           return result;
       } catch (error) {
           console.error('Erreur dans getCellDataSimple:', error);
           // Retourner des valeurs par défaut en cas d'erreur
           return {
               employee_code: elementData ? elementData.employeeCode : null,
               employee_id: elementData ? elementData.employeeId : null,
               assignment_id: elementData ? elementData.assignmentId : null,
               is_special: false,
               day_index: 0,
               period: 'am',
               site_code: 'MLE',
               site_name: 'Mont Légia'
           };
       }
   }
   
   function getPlanningId() {
       // L'URL peut être /web/planning/123 ou /planning/123
       const match = window.location.pathname.match(/\/(?:web\/)?planning\/(\d+)/);
       return match ? parseInt(match[1]) : null;
   }
   
   /* ================================
      SAUVEGARDE SERVEUR
      ================================ */
   
   // Nouvelle fonction avec file d'attente et rollback
   function saveToServerWithRollback(operation, source, target, stateBefore, rollbackCallback) {
       // Ajouter à la file d'attente
       operationQueue.push({
           operation,
           source,
           target,
           stateBefore,
           rollbackCallback
       });
   
       // Traiter la file d'attente
       processOperationQueue();
   }
   
   function processOperationQueue() {
       // Si une opération est déjà en cours, attendre
       if (isProcessingOperation) {
           return;
       }
   
       // Si la file est vide, ne rien faire
       if (operationQueue.length === 0) {
           return;
       }
   
       // Récupérer la prochaine opération
       const operationData = operationQueue.shift();
       isProcessingOperation = true;
   
       const planningId = getPlanningId();
       if (!planningId) {
           showNotification('Erreur: Planning non trouvé', 'error');
           if (operationData.rollbackCallback) {
               operationData.rollbackCallback();
           }
           isProcessingOperation = false;
           processOperationQueue(); // Traiter la prochaine opération
           return;
       }
   
       // Valider les données avant envoi
       if (!operationData.source || !operationData.target) {
           showNotification('Erreur: Données invalides', 'error');
           if (operationData.rollbackCallback) {
               operationData.rollbackCallback();
           }
           isProcessingOperation = false;
           processOperationQueue();
           return;
       }
   
       const data = {
           operation: operationData.operation,
           planning_id: planningId,
           source: operationData.source,
           target: operationData.target
       };
   
       // Format JSON-RPC pour Odoo
       const payload = {
           jsonrpc: "2.0",
           method: "call",
           params: data,
           id: Math.floor(Math.random() * 1000000)
       };
   
       // Timeout pour éviter les attentes infinies
       const timeoutId = setTimeout(() => {
           showNotification('Erreur: Timeout de connexion', 'error');
           if (operationData.rollbackCallback) {
               operationData.rollbackCallback();
           }
           isProcessingOperation = false;
           processOperationQueue();
       }, 10000); // 10 secondes de timeout
   
       fetch('/planning/update_assignment', {
           method: 'POST',
           headers: {
               'Content-Type': 'application/json',
               'X-Requested-With': 'XMLHttpRequest'
           },
           body: JSON.stringify(payload)
       })
           .then(response => {
               clearTimeout(timeoutId);
               if (!response.ok) {
                   throw new Error(`HTTP error! status: ${response.status}`);
               }
               return response.json();
           })
           .then(result => {
               // Gérer le format JSON-RPC
               const actualResult = result.result || result;
   
               if (actualResult && actualResult.success) {
                   showNotification('Modification sauvegardée', 'success');
               } else {
                   showNotification('Erreur: ' + (actualResult.error || 'Inconnu'), 'error');
                   // Rollback en cas d'erreur
                   if (operationData.rollbackCallback) {
                       operationData.rollbackCallback();
                   }
               }
           })
           .catch(error => {
               clearTimeout(timeoutId);
               console.error('Erreur lors de la sauvegarde:', error);
               showNotification('Erreur de connexion: ' + error.message, 'error');
               // Rollback en cas d'erreur
               if (operationData.rollbackCallback) {
                   operationData.rollbackCallback();
               }
           })
           .finally(() => {
               isProcessingOperation = false;
               // Traiter la prochaine opération dans la file
               processOperationQueue();
           });
   }
   
   // Fonction de rollback pour swap
   function rollbackSwap(stateBefore) {
       if (!stateBefore || !stateBefore.source || !stateBefore.target) {
           return;
       }
   
       try {
           // Restaurer l'état source
           if (stateBefore.source.element) {
               stateBefore.source.element.textContent = stateBefore.source.textContent;
               if (stateBefore.source.employeeId) {
                   stateBefore.source.element.setAttribute('data-employee-id', stateBefore.source.employeeId);
               }
               // Les assignment-id n'ont pas été modifiés, donc pas besoin de les restaurer
               if (stateBefore.source.color) {
                   stateBefore.source.element.setAttribute('data-color', stateBefore.source.color);
               }
           }
   
           // Restaurer l'état target
           if (stateBefore.target.element) {
               stateBefore.target.element.textContent = stateBefore.target.textContent;
               if (stateBefore.target.employeeId) {
                   stateBefore.target.element.setAttribute('data-employee-id', stateBefore.target.employeeId);
               }
               // Les assignment-id n'ont pas été modifiés, donc pas besoin de les restaurer
               if (stateBefore.target.color) {
                   stateBefore.target.element.setAttribute('data-color', stateBefore.target.color);
               }
           }
   
           applyEmployeeColors();
           showNotification('Modification annulée - état restauré', 'info');
       } catch (error) {
           console.error('Erreur lors du rollback:', error);
           showNotification('Erreur lors de la restauration - veuillez recharger la page', 'error');
       }
   }
   
   // Fonction de rollback pour move
   function rollbackMove(stateBefore) {
       if (!stateBefore) {
           return;
       }
   
       try {
           // Restaurer le wrapper source
           if (stateBefore.sourceWrapper && stateBefore.sourceCell) {
               stateBefore.sourceCell.appendChild(stateBefore.sourceWrapper.cloneNode(true));
           }
   
           // Supprimer le code créé dans la cellule cible
           if (stateBefore.targetCell) {
               const wrapper = stateBefore.targetCell.querySelector('.assignment-wrapper');
               if (wrapper) {
                   wrapper.remove();
               }
           }
   
           applyEmployeeColors();
           showNotification('Modification annulée - état restauré', 'info');
       } catch (error) {
           console.error('Erreur lors du rollback:', error);
           showNotification('Erreur lors de la restauration - veuillez recharger la page', 'error');
       }
   }
   
   // Fonction pour réinitialiser le drag & drop uniquement pour certaines cellules
   function reinitializeDragAndDropForCells(cells) {
       cells.forEach(cell => {
           const code = cell.querySelector('.assignment-code');
           if (code) {
               code.draggable = true;
               code.style.cursor = 'grab';
               
               // Vérifier si déjà initialisé
               if (!code.hasAttribute('data-drag-initialized')) {
                   const dragStartHandler = (e) => handleDragStart(e);
                   const dragEndHandler = (e) => handleDragEnd(e);
                   
                   code.addEventListener('dragstart', dragStartHandler);
                   code.addEventListener('dragend', dragEndHandler);
                   code.setAttribute('data-drag-initialized', 'true');
               }
           }
       });
   }
   
   // Ancienne fonction conservée pour compatibilité (mais utilise maintenant la nouvelle)
   function saveToServer(operation, source, target) {
       saveToServerWithRollback(operation, source, target, null, null);
   }
   
   /* ================================
      BOUTONS ET NOTIFICATIONS
      ================================ */
   
   function initializeButtons() {
       const printBtn = document.getElementById('btn-print');
       if (printBtn) {
           printBtn.addEventListener('click', () => window.print());
       }
   
       const exportBtn = document.getElementById('btn-export');
       if (exportBtn) {
           exportBtn.addEventListener('click', () => {
               showNotification('Export en cours de développement', 'info');
           });
       }
   }
   
   function showNotification(message, type) {
       // Supprimer notifications existantes
       document.querySelectorAll('.planning-notification').forEach(n => n.remove());
   
       const notification = document.createElement('div');
       notification.className = `alert alert-${type} planning-notification`;
       notification.style.cssText = `
           position: fixed;
           top: 20px;
           right: 20px;
           z-index: 1050;
           padding: 12px 20px;
           border-radius: 6px;
           box-shadow: 0 4px 12px rgba(0,0,0,0.15);
           min-width: 300px;
       `;
       notification.innerHTML = `
           ${message}
           <button type="button" style="margin-left: 10px;" onclick="this.parentNode.remove()">×</button>
       `;
   
       document.body.appendChild(notification);
   
       setTimeout(() => notification.remove(), 3000);
   }
   
   /* ================================
      GESTION DES CONFLITS ENTRE DRAG & DROP ET MENU CONTEXTUEL
      ================================ */
   
   function handleContextMenuConflicts() {
       // Fermer le menu contextuel lors du début d'un drag
       document.addEventListener('dragstart', function () {
           if (typeof closeContextMenu === 'function') {
               closeContextMenu();
           }
       });
   
       // Fermer le menu contextuel lors du scroll
       document.addEventListener('scroll', function () {
           if (typeof closeContextMenu === 'function') {
               closeContextMenu();
           }
       }, true);
   
       // Fermer le menu contextuel lors du redimensionnement
       window.addEventListener('resize', function () {
           if (typeof closeContextMenu === 'function') {
               closeContextMenu();
           }
       });
   }
   
   /* ================================
      FONCTIONS D'INTÉGRATION ET VÉRIFICATION
      ================================ */
   
   function ensureContextMenuIntegration() {
       const checks = {
           contextMenuAvailable: typeof initializeContextMenu === 'function',
           cellsFound: document.querySelectorAll('.assignment-cell').length > 0,
           codesFound: document.querySelectorAll('.assignment-code').length > 0,
           getColorsAvailable: typeof getEmployeeColors === 'function'
       };
   
       const allChecksPass = Object.values(checks).every(check => check);
   
       return allChecksPass;
   }
   
   /* ================================
      FONCTIONS DE DEBUG ET DÉVELOPPEMENT
      ================================ */
   
   function debugPlanningState() {
       const cells = document.querySelectorAll('.assignment-cell');
       const codes = document.querySelectorAll('.assignment-code');
   
       return {
           cells: cells.length,
           codes: codes.length,
           contextMenuAvailable: typeof initializeContextMenu === 'function',
           dragActive: dragSource !== null,
           contextMenuCreated: !!contextMenu
       };
   }
   
   function cleanupPlanningEvents() {
       // Nettoyer tous les event listeners pour éviter les fuites mémoire
       document.querySelectorAll('.assignment-cell').forEach(cell => {
           const listeners = dragAndDropListeners.get(cell);
           if (listeners) {
               cell.removeEventListener('dragover', listeners.dragover);
               cell.removeEventListener('dragenter', listeners.dragenter);
               cell.removeEventListener('dragleave', listeners.dragleave);
               cell.removeEventListener('drop', listeners.drop);
               dragAndDropListeners.delete(cell);
           }
       });
   
       // Réinitialiser les variables globales
       dragSource = null;
       operationQueue = [];
       isProcessingOperation = false;
       lastOperationState = null;
   }
   
   function planningControlPanel() {
       return {
           debugPlanningState: 'Affiche l\'état du planning',
           cleanupPlanningEvents: 'Nettoie les événements',
           ensureContextMenuIntegration: 'Vérifie l\'intégration',
           applyEmployeeColors: 'Réapplique les couleurs',
           initializeDragAndDrop: 'Réinitialise le drag&drop',
           initializeContextMenu: 'Réinitialise le menu contextuel'
       };
   }
   
   /* ================================
      EXPOSER LES FONCTIONS GLOBALEMENT
      ================================ */
   
   // Exposer les fonctions de debug globalement
   window.debugPlanningState = debugPlanningState;
   window.cleanupPlanningEvents = cleanupPlanningEvents;
   window.planningControlPanel = planningControlPanel;
   window.initializeContextMenu = initializeContextMenu;
   window.closeContextMenu = closeContextMenu;
   
   /* ================================
      ANIMATIONS ET STYLES CSS INLINE
      ================================ */
   
   // Ajouter les animations CSS manquantes
   const style = document.createElement('style');
   style.textContent = `
   @keyframes contextMenuFadeIn {
       from {
           opacity: 0;
           transform: scale(0.95) translateY(-8px);
       }
       to {
           opacity: 1;
           transform: scale(1) translateY(0);
       }
   }
   
   .assignment-cell:empty:hover::after {
       content: "Clic droit";
       position: absolute;
       top: 50%;
       left: 50%;
       transform: translate(-50%, -50%);
       font-size: 0.65rem;
       color: #1e3a8a;
       font-weight: 500;
       white-space: nowrap;
       opacity: 0.8;
       pointer-events: none;
       background: rgba(255, 255, 255, 0.9);
       padding: 2px 6px;
       border-radius: 4px;
       border: 1px solid #d1d5db;
   }
   
   .drag-notification {
       position: fixed;
       top: 80px;
       right: 20px;
       z-index: 1060;
       padding: 12px 20px;
       border-radius: 6px;
       box-shadow: 0 4px 12px rgba(0,0,0,0.15);
       min-width: 300px;
       background: white;
       border: 1px solid #d1d5db;
   }
   
   .drag-notification.info {
       border-left: 4px solid #0ea5e9;
       background: rgba(240, 249, 255, 0.95);
   }
   `;
   
   document.head.appendChild(style);