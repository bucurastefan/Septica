/**
 * Șeptică - Game Interactivity Script
 * Handles card interactions, animations, and game mechanics
 */

// Initialize socket connection
const socket = io();
let myCards = [];
let currentTrick = [];
let isMyTurn = false;
let myPosition = null;
let lobbyCode = null;

document.addEventListener('DOMContentLoaded', function() {
    // Get lobby code from hidden input
    lobbyCode = document.getElementById('lobby-code').value;
    if (!lobbyCode) {
        console.error('No lobby code found!');
        return;
    }

    // Remove existing interval if any
    if (window.turnInterval) {
        clearInterval(window.turnInterval);
    }

    // Join game room and initialize
    socket.emit('join_lobby_room', { lobby_code: lobbyCode });
    socket.emit('initialize_game', { lobby_code: lobbyCode });

    // Socket event listeners
    socket.on('game_state_update', handleGameStateUpdate);
    socket.on('game_error', handleGameError);
});

function handleGameStateUpdate(gameState) {
    console.log('Received game state:', gameState);
    if (!gameState) return;

    myCards = gameState.hand || [];
    currentTrick = gameState.current_trick || [];
    isMyTurn = gameState.current_player === gameState.position;
    myPosition = gameState.position;

    updateGameDisplay(gameState);
}

function handleGameError(data) {
    console.error('Game error:', data.message);
    alert(data.message);
}

function updateGameDisplay(gameState) {
    try {
        // Update scores and trump
        updateScoresAndTrump(gameState);
        
        // Update player's hand
        updatePlayerHand(gameState.hand || []);
        
        // Update center pile
        updateCenterPile(gameState.current_trick || []);
        
        // Update player areas and hands based on current turn
        updatePlayerTurnStates(gameState.current_player, gameState.position);
        
    } catch (error) {
        console.error('Error updating game display:', error);
    }
}

function updateScoresAndTrump(gameState) {
    const team1Score = document.querySelector('.team1-score');
    const team2Score = document.querySelector('.team2-score');
    const trumpSuit = document.querySelector('.trump-suit');
    const deckCount = document.querySelector('.cards-in-deck');

    if (team1Score) team1Score.textContent = gameState.scores?.[0] || 0;
    if (team2Score) team2Score.textContent = gameState.scores?.[1] || 0;
    if (trumpSuit) trumpSuit.innerHTML = `Trump: ${getSuitSymbol(gameState.trump_suit)}`;
    if (deckCount) deckCount.textContent = gameState.cards_in_deck || 0;
}

function updatePlayerHand(cards) {
    const playerHand = document.querySelector('.player-hand.me');
    if (!playerHand) return;

    playerHand.innerHTML = '';
    cards.forEach((card, index) => {
        const cardElement = createCardElement(card, index);
        // Only allow card interaction if it's player's turn
        cardElement.classList.toggle('playable', isMyTurn);
        playerHand.appendChild(cardElement);
    });
}

function updateCenterPile(currentTrick) {
    const centerPile = document.querySelector('.center-pile');
    if (!centerPile) return;

    centerPile.innerHTML = '';
    currentTrick.forEach((playedCard, index) => {
        const cardElement = createCardElement(playedCard[1], undefined, true);
        cardElement.style.zIndex = index;
        centerPile.appendChild(cardElement);
    });
}

function createCardElement(card, index, isCenter = false) {
    const cardDiv = document.createElement('div');
    cardDiv.className = `playing-card ${card.suit}`;
    
    // Add center-card class instead of inline styles
    if (isCenter) {
        cardDiv.classList.add('center-card');
    }
    
    cardDiv.innerHTML = `
        <div class="card-value">${card.value}</div>
        <div class="card-suit">${getSuitSymbol(card.suit)}</div>
    `;
    
    if (!isCenter && index !== undefined) {
        // Only add click handler if it's player's turn
        if (isMyTurn) {
            cardDiv.classList.add('playable');
            cardDiv.onclick = () => playCard(index);
        }
    }
    
    return cardDiv;
}

function playCard(index) {
    if (!isMyTurn) return;
    
    socket.emit('play_card', {
        lobby_code: lobbyCode,
        card_index: index
    });
}

function getSuitSymbol(suit) {
    const symbols = {
        'hearts': '♥',
        'diamonds': '♦',
        'clubs': '♣',
        'spades': '♠'
    };
    return symbols[suit] || suit;
}