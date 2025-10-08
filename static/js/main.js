let manualDeltas = [];

function getParams() {
  const params = ['V', 'K', 'T', 'sigma', 'r'].reduce((acc, id) => {
    const el = document.getElementById(id);
    acc[id] = el ? el.value : null;
    return acc;
  }, {});
  
  const mode = document.getElementById('delta-mode').value;
  params['delta-mode'] = mode;

  if (mode === 'auto') {
      params.delta = document.getElementById('delta-auto').value;
  } else {
      // Limit to the number of periods based on T
      const T_val = parseFloat(params.T);
      const n_periods = Math.round(T_val);
      // Only send up to n_periods values (t=0 to t=n-1). The final value (t=n) is always 1.0.
      params.delta = manualDeltas.slice(0, n_periods).join(',');
  }

  return params;
}

function showMessageBox(message, type = 'error') {
    const messageBox = document.createElement('div');
    messageBox.style.cssText = `position: fixed; top: 20px; left: 50%; transform: translateX(-50%); background-color: ${type === 'error' ? '#f44336' : '#4CAF50'}; color: white; padding: 15px; border-radius: 8px; box-shadow: 0 4px 8px rgba(0,0,0,0.2); z-index: 1000; font-family: 'Arial', sans-serif; opacity: 0; transition: opacity 0.5s ease-in-out;`;
    messageBox.textContent = message;
    document.body.appendChild(messageBox);

    setTimeout(() => {
        messageBox.style.opacity = 1;
    }, 10);

    setTimeout(() => {
        messageBox.style.opacity = 0;
        messageBox.addEventListener('transitionend', () => messageBox.remove());
    }, 3000);
}

function updateDeltaInputs() {
    const mode = document.getElementById('delta-mode').value;
    const autoInput = document.getElementById('delta-auto');
    const autoLabel = document.getElementById('delta-auto-label');
    const manualBtn = document.getElementById('manual-delta-btn');

    if (mode === 'manual') {
        autoInput.style.display = 'none';
        autoLabel.style.display = 'none';
        manualBtn.style.display = 'block';
    } else {
        autoInput.style.display = 'block';
        autoLabel.style.display = 'block';
        autoLabel.textContent = 'Initial Cost of Delay (δ):';
        manualBtn.style.display = 'none';
    }
}

function showManualDeltaModal() {
    const T_val = parseFloat(document.getElementById('T').value);
    const n_periods = Math.round(T_val); 

    if (isNaN(n_periods) || n_periods <= 0) {
        showMessageBox("Please enter a valid Time to Maturity (T > 0) first.", 'error');
        return;
    }
    
    const inputsContainer = document.getElementById('manual-delta-inputs');
    inputsContainer.innerHTML = '';

    for (let t = 0; t <= n_periods; t++) {
        const div = document.createElement('div');
        
        let labelText = `Cost of Delay (δ) for Period ${t} (Start of Year ${t + 1}):`;
        let inputValue = manualDeltas[t] !== undefined ? manualDeltas[t] : 0.0;
        let disabledAttr = '';
        
        if (t === n_periods) {
            labelText = `Cost of Delay (δ) for Period ${t} (Final Maturity):`;
            inputValue = 1.0;
            disabledAttr = 'disabled';
        }

        div.innerHTML = `
            <label for="delta-t-${t}">${labelText}</label>
            <input id="delta-t-${t}" type="number" step="any" min="0" value="${inputValue}" ${disabledAttr} required style="margin-bottom: 10px;">
        `;
        inputsContainer.appendChild(div);
    }
    
    document.getElementById('manual-delta-modal').style.display = 'block';
}

function saveManualDeltaInputs() {
    const T_val = parseFloat(document.getElementById('T').value);
    const n_periods = Math.round(T_val);

    const newDeltas = [];
    let hasError = false;

    for (let t = 0; t <= n_periods; t++) {
        const input = document.getElementById(`delta-t-${t}`);
        let val;

        if (t === n_periods) {
            val = 1.0; 
        } else {
            val = parseFloat(input.value);
        }

        if (isNaN(val) || val < 0) {
            showMessageBox(`Invalid value for Period ${t}. Must be a non-negative number.`, 'error');
            hasError = true;
            break;
        }
        newDeltas.push(val);
    }

    if (!hasError) {
        manualDeltas = newDeltas;
        document.getElementById('manual-delta-modal').style.display = 'none';
        showMessageBox(`Manual Cost of Delay saved for ${n_periods + 1} periods (t=0 to t=N).`, 'success');
    }
}

async function callApi(download = false) {
  const params = getParams();
  
  if (params['delta-mode'] === 'auto' && !params.delta) {
      showMessageBox(`Please enter an Initial Cost of Delay (δ).`);
      return;
  }
  
  if (params['delta-mode'] === 'manual') {
      const T_val = parseFloat(params.T);
      const n_periods = Math.round(params.T);
      if (manualDeltas.length < n_periods) {
          showMessageBox(`Manual mode requires ${n_periods} \\delta values (t=0 to t=${n_periods-1}). Please set them.`, 'error');
          return;
      }
  }

  const requiredFields = ['V', 'K', 'T', 'sigma', 'r'];
  const missing = requiredFields.filter(k => !params[k]);

  if (missing.length > 0) {
    showMessageBox(`Please fill in all required fields: ${missing.join(', ')}.`);
    return;
  }
  
  params.n = Math.round(parseFloat(params.T));
  if (params.n === 0) {
      params.n = 1;
  }

  if (download) params.export = 'excel';

  try {
    const res = await fetch('/calculate', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(params),
    });

    if (download) {
      if (!res.ok) throw new Error(`Download failed (status ${res.status})`);
      const blob = await res.blob();
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement('a');
      a.href     = url;
      a.download = 'tree.xlsx';
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      showMessageBox('Export successful!', 'success');
      return;
    }

    if (!res.ok) {
      let errMsg = `Error ${res.status}`;
      try {
        const errJson = await res.json();
        if (errJson.error) errMsg = errJson.error;
      } catch {}
      throw new Error(errMsg);
    }

    const json = await res.json();
    const val  = json.summary.initial_option_value;
    
    document.getElementById('option-value').innerHTML =
        `Option Value: ${parseFloat(val).toFixed(4)} €1000s`;
    
    showMessageBox('Calculation successful!', 'success');

    if (json.sensitivity) {
        renderSensitivityDashboard(json.sensitivity); 
    }
  }
  catch (err) {
    document.getElementById('option-value').textContent =
      `⚠️ ${err.message}`;
    showMessageBox(`Calculation error: ${err.message}`);
  }
}

// Function to update user profile display
function updateUserProfile(user) {
    const userInfoDiv = document.querySelector('.user-info');
    
    if (user.username && user.username !== 'Guest') {
        // Update display text inside the dropdown content
        document.getElementById('profile-username').textContent = user.username;
        document.getElementById('profile-email').textContent = user.email;
        
        // Update user icon display
        const userIcon = document.getElementById('user-icon');
        userIcon.textContent = `👤 ${user.username}`;
        
        // Setup dropdown toggle
        userIcon.addEventListener('click', (e) => {
            e.preventDefault();
            document.getElementById('user-dropdown').classList.toggle('show');
        });
        
        // Setup history button
        document.getElementById('show-history-btn').addEventListener('click', showHistoryModal);
    } else {
        // Not logged in or guest view
        // Ensure i-button is not displayed for guest user if you want
        // If you want to hide the i-button for guests, you'd handle it here.
        // For now, assume it stays visible for application info.
        const infoBtn = document.getElementById('info-btn');
        if (infoBtn) {
           // We keep the info button visible for all users/guests
           userInfoDiv.innerHTML = '';
           userInfoDiv.appendChild(infoBtn);
           const loginLink = document.createElement('a');
           loginLink.href = "/login";
           loginLink.style.cssText = "color: white; text-decoration: none;";
           loginLink.textContent = "Login";
           userInfoDiv.appendChild(loginLink);
        } else {
           userInfoDiv.innerHTML = `<a href="/login" style="color: white; text-decoration: none;">Login</a>`;
        }
    }
}

// Function to fetch and display history
async function showHistoryModal() {
    document.getElementById('user-dropdown').classList.remove('show');
    const historyList = document.getElementById('history-list');
    historyList.innerHTML = 'Loading history...';
    document.getElementById('calculation-details').style.display = 'none';

    try {
        const res = await fetch('/api/user/history');
        if (!res.ok) throw new Error('Failed to fetch history. You might need to log in again.');
        
        const history = await res.json();
        
        historyList.innerHTML = '';
        if (history.length === 0) {
            historyList.innerHTML = '<p>No previous calculations found.</p>';
        } else {
            history.forEach(calc => {
                const item = document.createElement('div');
                item.className = 'history-item';
                item.dataset.calc = JSON.stringify(calc);
                // Use simple text labels for symbols in history list
                item.innerHTML = `
                    <div>
                        <p><strong>${calc.timestamp}</strong></p>
                        <p style="font-size: 0.8em; color: #666;">T=${calc.input_params['Time to Maturity T']}, Volatility=${calc.input_params.Volatility}</p>
                    </div>
                    <p class="highlight-value">C\u2080: ${parseFloat(calc.initial_option_value).toFixed(4)} €1000s</p>
                `;
                item.addEventListener('click', () => showCalculationDetails(item));
                historyList.appendChild(item);
            });
        }
        document.getElementById('history-modal').style.display = 'block';
    } catch (error) {
        historyList.innerHTML = `<p style="color: red;">Error loading history: ${error.message}</p>`;
    }
}

// Function to display details of a selected history item
function showCalculationDetails(itemElement) {
    // Clear previous highlights
    document.querySelectorAll('.history-item').forEach(el => el.classList.remove('selected'));
    itemElement.classList.add('selected');
    
    const calc = JSON.parse(itemElement.dataset.calc);
    const detailsDiv = document.getElementById('calculation-details');
    
    document.getElementById('detail-timestamp').textContent = calc.timestamp;
    
    // Format input parameters nicely for display
    let inputStr = '';
    const inputs = calc.input_params;
    
    // Order and display with the new full names
    const fields = [
        'Asset Value V', 
        'Exercise Cost K', 
        'Time to Maturity T', 
        'Volatility', 
        'Risk-free Rate r'
    ];

    for (const key of fields) {
        if (inputs[key] !== undefined) {
             inputStr += `${key}: ${inputs[key]}\n`;
        }
    }
    
    // Handle Delta display
    if (inputs['Delta Mode'] === 'auto') {
        inputStr += `Cost of Delay (Auto/t=0): ${inputs['Cost of Delay (t=0)']}\n`;
    } else {
        // Join the manual deltas array for display
        const manualDeltas = inputs['Cost of Delay (Manual Mode)'];
        const manualDeltasStr = Array.isArray(manualDeltas) ? manualDeltas.join(', ') : 'N/A';
        inputStr += `Cost of Delay (Manual Mode): ${manualDeltasStr}\n`;
    }
    
    document.getElementById('detail-inputs').textContent = inputStr;
    
    // Highlighted optional value
    document.getElementById('detail-option-value').textContent = `${parseFloat(calc.initial_option_value).toFixed(4)} €1000s`;

    detailsDiv.style.display = 'block';
}


function renderSensitivityDashboard(sensitivityData) {
    
    // FIX 1: Restore delta symbol (\u03b4) in the second chart title.
    renderLineChart('line-chart-v-sigma', sensitivityData.line_chart_v_sigma, 'Volatility', 'Option Value Sensitivity: Asset Value (V) vs. Volatility');
    renderLineChart('line-chart-delta-sigma', sensitivityData.line_chart_delta_sigma, 'Volatility', 'Volatility vs. \u03b4 Impact on Option Value');
    renderTornadoChart('tornado-chart', sensitivityData.tornado, sensitivityData.base_option_value);
    renderSpiderChart('spider-chart', sensitivityData.spider);
}

// Charting Logic 

function renderLineChart(canvasId, chartData, xLabel, title) {
    const ctx = document.getElementById(canvasId).getContext('2d');
    const colors = ['#4CAF50', '#007bff', '#f44336']; 
    
    // Extract and format datasets
    const datasets = Object.keys(chartData.data).map((key, index) => {
        // Correctly replace "Cost of Delay=" with the delta symbol for the series label
        let label = key.replace(/Cost of Delay=(.*?)/, '\u03b4=$1');
        
        return {
            key: key, // Store original key for sorting
            label: label,
            data: chartData.data[key],
            borderColor: colors[index % colors.length],
            tension: 0.1, 
            fill: false,
        };
    });

    // CRITICAL FIX: Sort datasets based on the numerical value in the label.
    // This ensures V=570k appears before V=713k in the legend/chart drawing order (Ascending).
    datasets.sort((a, b) => {
        // Regex to extract the first number, handling both V=XXXk and Cost of Delay=X.X% formats.
        const regex = /[-+]?([0-9]*\.[0-9]+|[0-9]+)/;
        
        let aMatch = a.key.match(regex);
        let bMatch = b.key.match(regex);
        
        // Extract value or default to 0
        let aVal = aMatch ? parseFloat(aMatch[0]) : 0;
        let bVal = bMatch ? parseFloat(bMatch[0]) : 0;
        
        // Ascending sort (Low to High)
        return aVal - bVal; 
    });


    if (window.Chart.getChart(canvasId)) {
        window.Chart.getChart(canvasId).destroy();
    }

    new Chart(ctx, {
        type: 'line',
        data: {
            labels: chartData.x_labels,
            datasets: datasets
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            // FIX 2: Remove chart title to avoid redundancy with the <h3> tag
            plugins: { title: { display: false } }, 
            scales: {
                x: { title: { display: true, text: xLabel } }, 
                y: { title: { display: true, text: 'Optional Value (€1000s)' } }
            }
        }
    });
}

function renderTornadoChart(canvasId, tornadoData, baseValue) {
    const ctx = document.getElementById(canvasId).getContext('2d');
    const sortedParams = Object.entries(tornadoData)
        .sort(([, a], [, b]) => (b.max - b.min) - (a.max - a.min));

    const labels = sortedParams.map(([name, ]) => name);
    const minValues = sortedParams.map(([, data]) => data.min);
    const barLengths = sortedParams.map(([, data]) => data.max - data.min);
    
    if (window.Chart.getChart(canvasId)) {
        window.Chart.getChart(canvasId).destroy();
    }

    new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [
                {
                    // This data set is invisible, only used for stacking offset
                    label: 'Start (Min)',
                    data: minValues,
                    backgroundColor: 'rgba(0, 0, 0, 0)', 
                    stack: 'stack1',
                },
                {
                    // This is the visible range bar
                    label: 'Range',
                    data: barLengths,
                    backgroundColor: '#4CAF50',
                    stack: 'stack1',
                    hoverBackgroundColor: '#45a049'
                }
            ]
        },
        options: {
            indexAxis: 'y',
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                // Hide chart title (redundant) and the legend (unwanted)
                title: { display: false }, 
                legend: { 
                    display: false,
                    onClick: (e) => { 
                        e.stopPropagation(); 
                    }
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            
                            const dataIndex = context.dataIndex;
                            // Retrieve the Min (Start) value from the first dataset (index 0)
                            const minVal = context.chart.data.datasets[0].data[dataIndex];
                            // Retrieve the Range value from the second dataset (index 1)
                            const rangeVal = context.chart.data.datasets[1].data[dataIndex];

                            if (context.datasetIndex === 0) {
                                // Label for Start (Min) segment
                                return `Start (Min): ${minVal.toFixed(4)}`;
                            } else {
                                // Label for Range segment
                                const maxVal = minVal + rangeVal;
                                return [`Range: ${rangeVal.toFixed(4)}`, `End (Max): ${maxVal.toFixed(4)}`];
                            }
                        }
                    }
                }
            }, // <-- END plugins
            scales: {
                x: {
                    stacked: true,
                    // FIX APPLIED: Restore display: true for the X-axis title
                    title: { 
                        display: true, 
                        text: 'Option Value (€1000s)' 
                    }
                },
                y: {
                    stacked: true
                }
            } // <-- END scales
        } // <-- END options
    });
}

function renderSpiderChart(canvasId, spiderData) {
    const ctx = document.getElementById(canvasId).getContext('2d');
    
    const labels = Object.keys(spiderData);
    const dataValues = Object.values(spiderData);

    if (window.Chart.getChart(canvasId)) {
        window.Chart.getChart(canvasId).destroy();
    }
    
    new Chart(ctx, {
        type: 'radar',
        data: {
            labels: labels,
            datasets: [{
                label: 'Relative Sensitivity (% Change)',
                data: dataValues,
                backgroundColor: 'rgba(76, 175, 80, 0.4)', 
                borderColor: '#4CAF50',
                pointBackgroundColor: '#4CAF50',
                pointBorderColor: '#fff',
                pointHoverBackgroundColor: '#fff',
                pointHoverBorderColor: '#4CAF50'
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                title: { display: false } // FIX 2: Remove chart title
            },
            scales: {
                r: {
                    angleLines: { display: false },
                    suggestedMin: 0,
                    suggestedMax: Math.max(...dataValues) * 1.2, 
                    pointLabels: { font: { size: 11 } }
                }
            }
        }
    });
}


window.addEventListener('DOMContentLoaded', () => {
  // NOTE: updateUserProfile is called via inline script in main.html

  // --- Info Modal Logic ---
  const infoBtn = document.getElementById('info-btn');
  const infoModal = document.getElementById('info-modal-overlay');
  const closeInfoModal = document.getElementById('close-info-modal');

  if (infoBtn && infoModal && closeInfoModal) {
      infoBtn.addEventListener('click', (event) => {
          // Prevents the window.onclick listener (which closes the user-dropdown) from immediately closing the modal
          event.stopPropagation();
          infoModal.style.display = 'block';
      });

      closeInfoModal.addEventListener('click', () => {
          infoModal.style.display = 'none';
      });
  }
  // --- End Info Modal Logic ---

  updateDeltaInputs();

  document.getElementById('run-btn')
           .addEventListener('click', () => callApi(false));
  document.getElementById('download-btn')
           .addEventListener('click', () => callApi(true));
  
  document.getElementById('delta-mode')
           .addEventListener('change', updateDeltaInputs);
  document.getElementById('manual-delta-btn')
           .addEventListener('click', showManualDeltaModal);
  document.getElementById('save-manual-delta')
           .addEventListener('click', saveManualDeltaInputs);
  document.getElementById('cancel-manual-delta')
           .addEventListener('click', () => {
              document.getElementById('manual-delta-modal').style.display = 'none';
           });
  
  document.getElementById('T').addEventListener('change', () => {
      manualDeltas = [];
  });
  
  // Close history modal listener
  document.getElementById('close-history-modal').addEventListener('click', () => {
      document.getElementById('history-modal').style.display = 'none';
  });

  // Close dropdown/modal on outside click
  window.onclick = function(event) {
    const userDropdown = document.getElementById("user-dropdown");
    const infoModal = document.getElementById('info-modal-overlay');

    // Handle user dropdown closing
    if (!event.target.closest('.user-info')) {
        if (userDropdown && userDropdown.classList.contains('show')) {
            userDropdown.classList.remove('show');
        }
    }

    // Close the info modal if clicked outside the content (on the overlay)
    if (event.target === infoModal) {
        infoModal.style.display = 'none';
    }
  }
});
