// static/js/app.js
document.addEventListener('DOMContentLoaded', function() {
    // Elements
    const analysisForm = document.getElementById('analysisForm');
    const uploadForm = document.getElementById('uploadForm');
    const analyzeBtn = document.getElementById('analyzeBtn');
    const chartContainer = document.getElementById('chartContainer');
    const chartTitle = document.getElementById('chartTitle');
    const statusText = document.getElementById('statusText');
    const zonesTable = document.getElementById('zonesTable');
    const loadingOverlay = document.getElementById('loadingOverlay');
    const thresholdSlider = document.getElementById('thresholdSlider');
    const thresholdValue = document.getElementById('thresholdValue');
    
    // Data source radio buttons
    const apiDataSource = document.getElementById('apiDataSource');
    const fileDataSource = document.getElementById('fileDataSource');
    const apiSettingsCard = document.getElementById('apiSettingsCard');
    const fileUploadCard = document.getElementById('fileUploadCard');
    
    // File upload elements
    const csvFileInput = document.getElementById('csvFile');
    const uploadBtn = document.getElementById('uploadBtn');
    const currentFileInfo = document.getElementById('currentFileInfo');
    const currentFileName = document.getElementById('currentFileName');
    const clearFileBtn = document.getElementById('clearFileBtn');
    const analyzeFileBtn = document.getElementById('analyzeFileBtn');
    
    // Update threshold value display
    thresholdSlider.addEventListener('input', function() {
        thresholdValue.textContent = `${this.value}%`;
    });
    
    // Toggle between API and File data sources
    apiDataSource.addEventListener('change', function() {
        if (this.checked) {
            apiSettingsCard.classList.remove('d-none');
            fileUploadCard.classList.add('d-none');
        }
    });
    
    fileDataSource.addEventListener('change', function() {
        if (this.checked) {
            apiSettingsCard.classList.add('d-none');
            fileUploadCard.classList.remove('d-none');
        }
    });
    
    // Form submission for API analysis
    analysisForm.addEventListener('submit', function(e) {
        e.preventDefault();
        analyzeStock();
    });
    
    // Form submission for file upload
    uploadForm.addEventListener('submit', function(e) {
        e.preventDefault();
        uploadCSVFile();
    });
    
    // Analyze already uploaded file
    analyzeFileBtn.addEventListener('click', function() {
        analyzeUploadedFile();
    });
    
    // Clear uploaded file
    clearFileBtn.addEventListener('click', function() {
        clearUploadedFile();
    });
    
    async function uploadCSVFile() {
        // Check if a file is selected
        if (!csvFileInput.files.length) {
            updateStatus('Please select a CSV file', 'danger');
            return;
        }
        
        const file = csvFileInput.files[0];
        
        // Check if it's a CSV file
        if (!file.name.endsWith('.csv')) {
            updateStatus('Please select a CSV file', 'danger');
            return;
        }
        
        // Show loading overlay
        loadingOverlay.classList.remove('d-none');
        updateStatus('Uploading file...', 'info');
        
        try {
            // Create form data
            const formData = new FormData();
            formData.append('csvFile', file);
            
            // Send to server
            const response = await fetch('/api/upload', {
                method: 'POST',
                body: formData
            });
            
            const data = await response.json();
            
            if (response.ok) {
                // Update UI to show current file
                currentFileName.textContent = `File: ${data.filename}`;
                currentFileInfo.classList.remove('d-none');
                csvFileInput.value = '';
                
                // Proceed to analyze the file
                analyzeUploadedFile();
            } else {
                throw new Error(data.error || 'Failed to upload file');
            }
        } catch (error) {
            console.error('Error:', error);
            updateStatus(`Upload error: ${error.message}`, 'danger');
            loadingOverlay.classList.add('d-none');
        }
    }
    
    async function clearUploadedFile() {
        try {
            const response = await fetch('/api/clear-upload', {
                method: 'POST'
            });
            
            if (response.ok) {
                // Reset UI
                currentFileInfo.classList.add('d-none');
                currentFileName.textContent = 'No file uploaded';
                csvFileInput.value = '';
                
                // Clear chart
                chartContainer.innerHTML = `
                    <div class="placeholder-container">
                        <i class="bi bi-file-earmark-spreadsheet placeholder-icon"></i>
                        <p>Upload a CSV file to analyze</p>
                    </div>
                `;
                
                // Clear zones table
                const tableBody = zonesTable.querySelector('tbody');
                tableBody.innerHTML = `
                    <tr class="placeholder-row">
                        <td colspan="6" class="text-center py-3">
                            No zones identified yet. Upload a CSV file to view zones.
                        </td>
                    </tr>
                `;
                
                updateStatus('File removed', 'info');
            }
        } catch (error) {
            console.error('Error:', error);
            updateStatus(`Error removing file: ${error.message}`, 'danger');
        }
    }
    
    async function analyzeUploadedFile() {
        // Get settings
        const settings = getSettings();
        
        // Show loading overlay
        loadingOverlay.classList.remove('d-none');
        updateStatus('Analyzing data...', 'info');
        
        try {
            // Send API request with uploaded file flag
            const response = await fetch('/api/analyze', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    use_uploaded_data: true,
                    threshold: settings.threshold / 100, // Convert from percentage
                    consol_window: settings.consolWindow,
                    detection_method: settings.detectionMethod,
                    require_volume: settings.requireVolume,
                    merge_zones: settings.mergeZones,
                    show_sma20: settings.showSMA20,
                    show_sma50: settings.showSMA50,
                    show_sma200: settings.showSMA200,
                    show_rsi: settings.showRSI,
                    show_supply: settings.showSupply,
                    show_demand: settings.showDemand,
                    zone_display: settings.zoneDisplay,
                    max_bars: settings.maxBars,
                    rsi_period: settings.rsiPeriod
                })
            });
            
            const data = await response.json();
            
            if (response.ok) {
                // Update the chart
                chartTitle.textContent = `${data.title} - ${data.interval} Timeframe`;
                updateChart(data.chart);
                
                // Update zones table
                updateZonesTable(data.zones);
                
                updateStatus('Analysis complete', 'success');
            } else {
                throw new Error(data.error || 'Failed to analyze data');
            }
        } catch (error) {
            console.error('Error:', error);
            chartContainer.innerHTML = `
                <div class="placeholder-container">
                    <i class="bi bi-exclamation-triangle placeholder-icon"></i>
                    <p>Error: ${error.message}</p>
                </div>
            `;
            updateStatus(`Error: ${error.message}`, 'danger');
        } finally {
            // Hide loading overlay
            loadingOverlay.classList.add('d-none');
        }
    }
    
    async function analyzeStock() {
        // Get form values
        const ticker = document.getElementById('ticker').value.trim().toUpperCase();
        const interval = document.getElementById('interval').value;
        const period = document.getElementById('period').value;
        
        // Get settings
        const settings = getSettings();
        
        if (!ticker) {
            updateStatus('Please enter a ticker symbol', 'danger');
            return;
        }
        
        // Show loading overlay
        loadingOverlay.classList.remove('d-none');
        updateStatus('Analyzing data...', 'info');
        
        try {
            // Send API request
            const response = await fetch('/api/analyze', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    ticker: ticker,
                    interval: interval,
                    period: period,
                    threshold: settings.threshold / 100, // Convert from percentage
                    consol_window: settings.consolWindow,
                    detection_method: settings.detectionMethod,
                    require_volume: settings.requireVolume,
                    merge_zones: settings.mergeZones,
                    show_sma20: settings.showSMA20,
                    show_sma50: settings.showSMA50,
                    show_sma200: settings.showSMA200,
                    show_rsi: settings.showRSI,
                    show_supply: settings.showSupply,
                    show_demand: settings.showDemand,
                    zone_display: settings.zoneDisplay,
                    max_bars: settings.maxBars,
                    rsi_period: settings.rsiPeriod,
                    use_uploaded_data: false
                })
            });
            
            const data = await response.json();
            
            if (response.ok) {
                // Update the chart
                chartTitle.textContent = `${data.title} - ${data.interval} Timeframe`;
                updateChart(data.chart);
                
                // Update zones table
                updateZonesTable(data.zones);
                
                updateStatus('Analysis complete', 'success');
            } else {
                throw new Error(data.error || 'Failed to analyze stock');
            }
        } catch (error) {
            console.error('Error:', error);
            chartContainer.innerHTML = `
                <div class="placeholder-container">
                    <i class="bi bi-exclamation-triangle placeholder-icon"></i>
                    <p>Error: ${error.message}</p>
                </div>
            `;
            updateStatus(`Error: ${error.message}`, 'danger');
        } finally {
            // Hide loading overlay
            loadingOverlay.classList.add('d-none');
        }
    }
    
    function updateChart(chartJson) {
        // Parse the JSON data from Plotly
        const parsedJson = JSON.parse(chartJson);
        
        // Create an empty div for the chart
        chartContainer.innerHTML = '';
        
        // Create plot
        Plotly.newPlot(chartContainer, parsedJson.data, parsedJson.layout, {
            responsive: true,
            displayModeBar: true,
            modeBarButtonsToRemove: ['lasso2d', 'select2d']
        });
        
        // Resize event
        window.addEventListener('resize', function() {
            Plotly.Plots.resize(chartContainer);
        });
    }
    
    function updateZonesTable(zones) {
        // Clear table content
        const tableBody = zonesTable.querySelector('tbody');
        tableBody.innerHTML = '';
        
        if (zones.length === 0) {
            tableBody.innerHTML = `
                <tr class="placeholder-row">
                    <td colspan="6" class="text-center py-3">
                        No zones identified with current settings.
                    </td>
                </tr>
            `;
            return;
        }
        
        // Sort zones by strength
        zones.sort((a, b) => b[2].strength - a[2].strength);
        
        // Get current price (if available)
        let currentPrice = null;
        try {
            const chartData = Plotly.getData(chartContainer);
            if (chartData && chartData[0] && chartData[0].close) {
                currentPrice = chartData[0].close[chartData[0].close.length - 1];
            }
        } catch(e) {
            console.log('Could not get current price');
        }
        
        // Add zones to table (up to 10)
        zones.slice(0, 10).forEach(zone => {
            const [date, type, info] = zone;
            
            // Create row
            const row = document.createElement('tr');
            
            // Type cell with color
            const typeCell = document.createElement('td');
            typeCell.innerHTML = `<span class="${type.toLowerCase()}-color">${type}</span>`;
            
            // Price level cell with distance from current price
            const levelCell = document.createElement('td');
            const priceText = `${info.level.toFixed(2)}`;
            if (currentPrice) {
                const distance = Math.abs(info.level - currentPrice) / currentPrice * 100;
                levelCell.textContent = `${priceText} (${distance.toFixed(1)}% away)`;
            } else {
                levelCell.textContent = priceText;
            }
            
            // Strength cell
            const strengthCell = document.createElement('td');
            strengthCell.textContent = `${info.strength.toFixed(0)}%`;
            
            // Method cell
            const methodCell = document.createElement('td');
            methodCell.textContent = info.consolidation ? 'Consolidation' : 'Price Action';
            
            // Volume cell
            const volumeCell = document.createElement('td');
            if (info.volume && info.avg_volume) {
                const volRatio = info.volume / info.avg_volume;
                volumeCell.textContent = `${volRatio.toFixed(1)}x avg`;
            } else {
                volumeCell.textContent = 'N/A';
            }
            
            // Date cell
            const dateCell = document.createElement('td');
            dateCell.textContent = formatDate(date);
            
            // Add cells to row
            row.appendChild(typeCell);
            row.appendChild(levelCell);
            row.appendChild(strengthCell);
            row.appendChild(methodCell);
            row.appendChild(volumeCell);
            row.appendChild(dateCell);
            
            // Add row to table
            tableBody.appendChild(row);
        });
    }
    
    function formatDate(dateStr) {
        const date = new Date(dateStr);
        return date.toLocaleString();
    }
    
    function updateStatus(message, type = 'info') {
        statusText.textContent = message;
        
        // Update color based on type
        if (type === 'success') {
            statusText.style.color = '#26b067';
        } else if (type === 'danger') {
            statusText.style.color = '#b02e26';
        } else if (type === 'info') {
            statusText.style.color = '#3a6ea8';
        } else {
            statusText.style.color = '#9e9e9e';
        }
    }
    
    function getSettings() {
        return {
            // Zone Settings
            threshold: parseFloat(thresholdSlider.value),
            detectionMethod: document.getElementById('detectionMethod').value,
            consolWindow: parseInt(document.getElementById('consolWindow').value),
            requireVolume: document.getElementById('requireVolume').checked,
            mergeZones: document.getElementById('mergeZones').checked,
            
            // Display Settings
            showSupply: document.getElementById('showSupply').checked,
            showDemand: document.getElementById('showDemand').checked,
            zoneDisplay: document.getElementById('zoneDisplay').value,
            maxBars: parseInt(document.getElementById('maxBars').value),
            
            // Indicator Settings
            showSMA20: document.getElementById('showSMA20').checked,
            showSMA50: document.getElementById('showSMA50').checked,
            showSMA200: document.getElementById('showSMA200').checked,
            showRSI: document.getElementById('showRSI').checked,
            rsiPeriod: parseInt(document.getElementById('rsiPeriod').value)
        };
    }
    
    // Add help link for CSV format
    const csvHelpLink = document.createElement('button');
    csvHelpLink.className = 'btn btn-link btn-sm text-light p-0 ms-1';
    csvHelpLink.innerHTML = '<i class="bi bi-question-circle"></i>';
    csvHelpLink.title = 'CSV Format Help';
    csvHelpLink.setAttribute('data-bs-toggle', 'modal');
    csvHelpLink.setAttribute('data-bs-target', '#csvHelpModal');
    
    // Insert help link next to CSV upload label
    const csvFileLabel = document.querySelector('label[for="csvFile"]');
    csvFileLabel.appendChild(csvHelpLink);
    
    // Initialize with default settings
    updateStatus('Ready');
});
